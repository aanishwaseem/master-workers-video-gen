import redis
import boto3
import json
import os
import subprocess
import uuid
import time
import threading
import shutil

worker_id = str(uuid.uuid4())[:8]

REDIS_HOST = "192.168.100.5"
MINIO_ENDPOINT = "http://192.168.100.5:9000"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"

INPUT_BUCKET = "videos-input"
OUTPUT_BUCKET = "videos-output"

LOCAL_WORKDIR = "workdir"

os.makedirs(LOCAL_WORKDIR, exist_ok=True)

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

s3 = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

QUEUE_NAME = f"video_jobs:{worker_id}"

print(f"Worker Core {worker_id} started. Connecting...")

def heartbeat():
    while True:
        r.set(f"worker_heartbeat:{worker_id}", "alive", ex=15)
        time.sleep(5)

threading.Thread(target=heartbeat, daemon=True).start()

print(f"Listening on queue {QUEUE_NAME}...")

while True:
    data = r.blpop(QUEUE_NAME, timeout=10)
    if data is None:
        continue
    
    _, job_json = data
    job = json.loads(job_json)

    config = job["config"]
    video = job["video"]
    retries = job.get("retries", 0)

    print(f"Processing: {config} {video} (Retries: {retries})")

    local_path = os.path.join(LOCAL_WORKDIR, config, video)
    
    try:
        os.makedirs(local_path, exist_ok=True)
        prefix = f"{config}/{video}/"

        response = s3.list_objects_v2(Bucket=INPUT_BUCKET, Prefix=prefix)

        if "Contents" not in response:
            print("No files found for job")
            raise Exception("No source files in MinIO")

        for obj in response["Contents"]:
            key = obj["Key"]
            filename = key.split("/")[-1]
            if filename == "":
                continue

            dest = os.path.join(local_path, filename)
            s3.download_file(INPUT_BUCKET, key, dest)

        print("Running pipeline script...")
        
        # Log to Redis directly instead of local text files
        log_key = f"job:logs:{config}:{video}"
        r.delete(log_key)
        
        process = subprocess.Popen(
            ["python", "pipeline_script.py", local_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        for line in process.stdout:
            r.rpush(log_key, line.strip())
            print(line.strip())
            
        process.wait()
        
        if process.returncode != 0:
            raise Exception(f"Pipeline failed with exit code {process.returncode}")

        output_file = os.path.join(local_path, "result.mp4")
        
        # Point 2: Validate file size (>100KB)
        if os.path.exists(output_file) and os.path.getsize(output_file) > 100 * 1024:
            upload_key = f"{config}/{video}/result.mp4"
            s3.upload_file(output_file, OUTPUT_BUCKET, upload_key)
            print("Uploaded result:", upload_key)
            # Mark complete
            r.hset(f"job:status:{config}:{video}", "state", "completed")
        else:
            raise Exception("Result file missing or too small")

    except Exception as e:
        print(f"Job failed: {e}")
        r.hset(f"job:status:{config}:{video}", "state", "failed")
        r.hset(f"job:status:{config}:{video}", "error", str(e))
        
        # Retry logic (Point 1 transposed)
        if retries < 3:
            job["retries"] = retries + 1
            print("Re-queueing job...")
            r.rpush(QUEUE_NAME, json.dumps(job))
            
    finally:
        # Cleanup (Point 5 transposed)
        print(f"Cleaning local workspace for {video}...")
        try:
            shutil.rmtree(local_path)
        except Exception as e:
            print("Failed to clean up", e)

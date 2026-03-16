import redis
import boto3
import json
import os
import subprocess
import uuid
import time
import threading

worker_id = str(uuid.uuid4())[:8]


REDIS_HOST = "192.168.100.5"
QUEUE_NAME = "video_jobs"

MINIO_ENDPOINT = "http://192.168.100.5:9000"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"

INPUT_BUCKET = "videos-input"
OUTPUT_BUCKET = "videos-output"

LOCAL_WORKDIR = "workdir"

os.makedirs(LOCAL_WORKDIR, exist_ok=True)

r = redis.Redis(host=REDIS_HOST, port=6379)

s3 = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

print("Worker started. Waiting for jobs...")
def heartbeat():
    while True:
        r.set(f"worker:{worker_id}", time.time(), ex=15)
        time.sleep(5)

threading.Thread(target=heartbeat, daemon=True).start()

print("Worker ID:", worker_id)
while True:

    _, data = r.blpop(QUEUE_NAME)

    job = json.loads(data)

    config = job["config"]
    video = job["video"]

    print("Processing:", config, video)

    local_path = os.path.join(LOCAL_WORKDIR, config, video)
    os.makedirs(local_path, exist_ok=True)

    prefix = f"{config}/{video}/"

    response = s3.list_objects_v2(
        Bucket=INPUT_BUCKET,
        Prefix=prefix
    )

    if "Contents" not in response:
        print("No files found for job")
        continue

    for obj in response["Contents"]:

        key = obj["Key"]
        filename = key.split("/")[-1]

        if filename == "":
            continue

        dest = os.path.join(local_path, filename)

        print("Downloading", key)

        s3.download_file(INPUT_BUCKET, key, dest)

    print("Running pipeline script...")

    subprocess.run([
        "python",
        "pipeline_script.py",
        local_path
    ])

    output_file = os.path.join(local_path, "result.txt")

    if os.path.exists(output_file):

        upload_key = f"{config}/{video}/result.txt"

        s3.upload_file(
            output_file,
            OUTPUT_BUCKET,
            upload_key
        )

        print("Uploaded result:", upload_key)

    print("Job finished.\n")
import sys
import multiprocessing

# Windows RQ Fix: Map 'fork' to 'spawn' so the RQ module can import on Windows
if sys.platform == "win32":
    _orig_get_context = multiprocessing.get_context
    def _patched_get_context(method=None):
        if method == 'fork':
            method = 'spawn'
        return _orig_get_context(method)
    multiprocessing.get_context = _patched_get_context

multiprocessing.set_start_method('spawn', force=True)

import redis
from rq import Queue, SimpleWorker
import boto3
import json
import os
import subprocess
import uuid
import time
import threading
import shutil
from multiprocessing import Process
# ========== GLOBAL VARIABLES ==========
IDLE_TIMEOUT = 60  # seconds (1 minute)


# ========== GLOBAL CONFIG ==========

worker_id = str(uuid.uuid4())[:8]

REDIS_HOST = "127.0.0.1"
MINIO_ENDPOINT = "http://localhost:9000"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"

INPUT_BUCKET = "videos-input"
OUTPUT_BUCKET = "videos-output"

QUEUE_NAME = "video_jobs"

# Worker is 1 level before video-gen
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_GEN_DIR = os.path.join(BASE_DIR, "video-gen")

INPUT_FILES_DIR = os.path.join(VIDEO_GEN_DIR, "input_files")
OUTPUT_FILES_DIR = os.path.join(VIDEO_GEN_DIR, "output_files")

os.makedirs(INPUT_FILES_DIR, exist_ok=True)
os.makedirs(OUTPUT_FILES_DIR, exist_ok=True)

# ========== REDIS & MINIO ==========

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)
rq_redis = redis.Redis(host=REDIS_HOST, port=6379)
q = Queue(QUEUE_NAME, connection=rq_redis)

s3 = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

# ========== LOAD CONCURRENCY ==========

max_concurrency = 1
config_path = os.path.join(VIDEO_GEN_DIR, "config.json")

if os.path.exists(config_path):
    try:
        with open(config_path, "r") as f:
            v_config = json.load(f)
            max_concurrency = v_config.get("no_of_concurrent_generations", 1)
    except Exception as e:
        print("Failed to load config:", e)

print(f"Worker {worker_id} started. Concurrency: {max_concurrency}")

# ========== HEARTBEAT ==========

def heartbeat():
    while True:
        r.set(f"worker_heartbeat:{worker_id}", "alive", ex=15)
        time.sleep(5)

threading.Thread(target=heartbeat, daemon=True).start()

# ========== JOB PROCESSOR ==========

def process_job(job):
    folder = job["folder"]

    print(f"[{worker_id}] Processing {folder}")

    input_local_path = os.path.join(INPUT_FILES_DIR, folder)
    output_local_path = os.path.join(OUTPUT_FILES_DIR, folder)

    try:
        # -------- Download from MinIO --------
        prefix = f"{folder}/"
        response = s3.list_objects_v2(Bucket=INPUT_BUCKET, Prefix=prefix)

        if "Contents" not in response:
            raise Exception("No files found in MinIO")

        for obj in response["Contents"]:
            key = obj["Key"]
            relative_key = key[len(prefix):]

            if relative_key == "":
                continue

            dest = os.path.join(input_local_path, relative_key)
            os.makedirs(os.path.dirname(dest), exist_ok=True)

            s3.download_file(INPUT_BUCKET, key, dest)

        print(f"{folder} copied to video-gen/input_files")

        # -------- Run pipeline --------
        process = subprocess.Popen(
            ["python", "video_generation_script.py"],
            cwd=VIDEO_GEN_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        for line in process.stdout:
            print(f"[{folder}] {line.strip()}")

        process.wait()

        if process.returncode != 0:
            raise Exception("Pipeline failed")

        # -------- Wait for final MP4 --------
        result_file = os.path.join(output_local_path, "result.mp4")

        if not os.path.exists(result_file):
            raise Exception("Result file missing")

        if os.path.getsize(result_file) < 100 * 1024:
            raise Exception("Result file too small")

        # -------- Upload to MinIO --------
        upload_key = f"{folder}/result.mp4"
        s3.upload_file(result_file, OUTPUT_BUCKET, upload_key)

        print(f"{folder} uploaded to output bucket")

        r.hset(f"job:status:{folder}", "state", "completed")

    except Exception as e:
        print(f"{folder} failed:", e)
        r.hset(f"job:status:{folder}", "state", "failed")
        r.hset(f"job:status:{folder}", "error", str(e))
        raise e

    finally:
        # Cleanup only this job folders
        try:
            shutil.rmtree(input_local_path, ignore_errors=True)
            shutil.rmtree(output_local_path, ignore_errors=True)
        except:
            pass

# ========== MAIN LOOP ==========


def run_rq_worker():
    print(f"[{worker_id}] RQ Worker subprocess started.")

    try:
        worker = SimpleWorker([q], connection=rq_redis, name=f"renderer-{worker_id}")

        worker.work(
            burst=True,              # Exit when queue becomes empty
            max_idle_time=IDLE_TIMEOUT  # Exit if idle for 60 sec
        )

        print(f"[{worker_id}] Worker exited cleanly.")

    except Exception as e:
        print(f"[{worker_id}] Fatal worker error: {e}")
        os._exit(1)   # Immediately terminate process


def main():
    # Force 'spawn' method for Windows multiprocessing compatibility
    if sys.platform == "win32":
        try:
            multiprocessing.set_start_method('spawn', force=True)
        except RuntimeError:
            pass 

    print(f"Worker {worker_id} initializing {max_concurrency} parallel processes...")
    
    processes = []
    for i in range(max_concurrency):
        p = multiprocessing.Process(target=run_rq_worker)
        p.start()
        processes.append(p)
        print(f"-> Started Process Slot {i+1}")

    for p in processes:
        p.join()
if __name__ == "__main__":
    main()
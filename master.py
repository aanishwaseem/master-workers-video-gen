import multiprocessing
import sys
if sys.platform == "win32":
    _orig_get_context = multiprocessing.get_context
    def _patched_get_context(method=None):
        if method == 'fork':
            method = 'spawn'
        return _orig_get_context(method)
    multiprocessing.get_context = _patched_get_context

multiprocessing.set_start_method('spawn', force=True)
import redis
from rq import Queue, Retry
import boto3
import json
import os
import time
import atexit
import signal
from rq.registry import FailedJobRegistry, StartedJobRegistry, FinishedJobRegistry

CONFIG = {
    "max_retry_limit_per_video": 3,
}



REDIS_HOST = "127.0.0.1"
QUEUE_NAME = "video_jobs"

MINIO_ENDPOINT = "http://localhost:9000"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"
BUCKET = "videos-input"
CODE_BUCKET = "worker-code"

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)
rq_redis = redis.Redis(host=REDIS_HOST, port=6379)
q = Queue(QUEUE_NAME, connection=rq_redis)
failed_registry = FailedJobRegistry(queue=q)
started_registry = StartedJobRegistry(QUEUE_NAME, connection=rq_redis)
finished_registry = FinishedJobRegistry(QUEUE_NAME, connection=rq_redis)


def handle_sigterm(*args):
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)

s3 = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

print("Setting up code bucket...")
try:
    s3.head_bucket(Bucket=CODE_BUCKET)
except Exception:
    s3.create_bucket(Bucket=CODE_BUCKET)

print("Uploading latest worker scripts...")
s3.upload_file("worker_core.py", CODE_BUCKET, "worker_core.py")
if os.path.exists("tasks.py"):
    s3.upload_file("tasks.py", CODE_BUCKET, "tasks.py")

worker_keys = r.keys("worker_heartbeat:*")
workers = [key.split(":")[1] for key in worker_keys]


print(f"Found {len(workers)} workers: {workers}")

print("Starting Master Loop to monitor MinIO and Redis...")

# Load previous states if they exist

# Keep track of last known states
last_job_states = {}

while True:
    try:
        # 1. Retrieve current jobs in MinIO input bucket
        response = s3.list_objects_v2(Bucket=BUCKET)
        minio_jobs = set()
        if "Contents" in response:
            for obj in response["Contents"]:
                parts = obj["Key"].split("/")
                if len(parts) >= 2:
                    folder = parts[0]
                    minio_jobs.add(folder)

        # 2. Get jobs from Redis using Built-in RQ features (IDs = folders)
        queued_folders = set(q.job_ids)
        running_folders = set(started_registry.get_job_ids())
        done_folders = set(finished_registry.get_job_ids())
        failed_folders = set(failed_registry.get_job_ids())

        # 3. Check each job's status and print changes
        all_jobs = minio_jobs.union(queued_folders, running_folders, done_folders, failed_folders)
        for folder in all_jobs:
            if folder in done_folders:
                state = "completed"
            elif folder in failed_folders:
                state = "failed"
            elif folder in running_folders:
                state = "processing"
            elif folder in queued_folders:
                state = "queued"
            else:
                state = "unknown"

            last_state = last_job_states.get(folder)
            if last_state != state:
                print(f"[Master] Job {folder} status changed: {last_state} -> {state}")
                last_job_states[folder] = state

        # 4. Add new jobs that are not already known to RQ
        for folder in minio_jobs:
            if folder in queued_folders or folder in running_folders or folder in done_folders or folder in failed_folders:
                continue

            # Enqueue new job
            job_data = {"folder": folder}
            q.enqueue(
                "tasks.process_job", 
                job_data,
                job_id=folder,
                retry=Retry(max=CONFIG["max_retry_limit_per_video"])
            )
            print(f"[Master] Queued NEW job: {folder}")

    except Exception as e:
        print(f"[Master] Unexpected error in master loop: {e}")

    time.sleep(5)
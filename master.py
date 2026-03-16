import redis
import boto3
import json
import os
import time

REDIS_HOST = "localhost"
QUEUE_NAME = "video_jobs"

MINIO_ENDPOINT = "http://192.168.100.5:9000"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"
BUCKET = "videos-input"
CODE_BUCKET = "worker-code"

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

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

print("Uploading latest worker_core.py...")
s3.upload_file("worker_core.py", CODE_BUCKET, "worker_core.py")

print("Waiting for workers to come online...")
time.sleep(5)  # give bootstrapper workers a few seconds
worker_keys = r.keys("worker_heartbeat:*")
workers = [key.split(":")[1] for key in worker_keys]

if not workers:
    print("No workers found! Waiting 60s...")
    time.sleep(60)
    worker_keys = r.keys("worker_heartbeat:*")
    workers = [key.split(":")[1] for key in worker_keys]
    if not workers:
        print("Still no workers. Exiting.")
        exit(1)

print(f"Found {len(workers)} workers: {workers}")

print("Scanning MinIO bucket for jobs...")

response = s3.list_objects_v2(Bucket=BUCKET)

if "Contents" not in response:
    print("No files found.")
    exit()

jobs = set()

for obj in response["Contents"]:
    key = obj["Key"]

    parts = key.split("/")
    if len(parts) >= 2:
        config = parts[0]
        video = parts[1]
        jobs.add((config, video))

jobs_list = list(jobs)
total_jobs = len(jobs_list)

print(f"Dividing {total_jobs} among {len(workers)} workers...")

# Distribute jobs using round-robin
for idx, (config, video) in enumerate(jobs_list):
    job = {
        "config": config,
        "video": video,
        "retries": 0
    }
    
    assigned_worker = workers[idx % len(workers)]
    worker_queue = f"video_jobs:{assigned_worker}"

    r.rpush(worker_queue, json.dumps(job))
    print(f"Queued: {job} -> {worker_queue}")

print("Done.")
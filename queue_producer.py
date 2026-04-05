import multiprocessing
import sys

import collections
import collections.abc
collections.Callable = collections.abc.Callable

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
import signal
import uuid
import re
from rq.registry import FailedJobRegistry, StartedJobRegistry, FinishedJobRegistry

# Load config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(BASE_DIR, "config.json")
CONFIG = {}
if os.path.exists(config_path):
    with open(config_path, "r") as f:
        CONFIG = json.load(f)

REDIS_HOST = "127.0.0.1"
QUEUE_NAME = "video_jobs"

MINIO_ENDPOINT = "http://localhost:9000"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"
BUCKET = "videos-input"
CODE_BUCKET = "worker-code"


def handle_sigterm(*args):
    sys.exit(0)


def setup_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )


def setup_code_bucket(s3):
    print("Setting up code bucket...")
    try:
        s3.head_bucket(Bucket=CODE_BUCKET)
    except Exception:
        s3.create_bucket(Bucket=CODE_BUCKET)


def upload_worker_scripts(s3):
    print("Uploading latest worker scripts...")
    worker_scripts_dir = "worker_runtime_scripts"
    if not os.path.exists(worker_scripts_dir):
        print(f"Warning: Directory '{worker_scripts_dir}' not found. No scripts uploaded.")
        return
        
    for root, dirs, files in os.walk(worker_scripts_dir):
        for file in files:
            local_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_path, worker_scripts_dir)
            s3_key = relative_path.replace(os.sep, '/')
            
            s3.upload_file(local_path, CODE_BUCKET, s3_key)
            print(f"  Uploaded {s3_key}")


def backup_jobs_locally(s3, final_jobs):
    if not CONFIG.get("keep_backup_of_input_materials", False):
        return
    
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(BASE_DIR, "backup", timestamp)
    
    print(f"[Master] Backing up input materials to local folder: {backup_dir}...")
    for folder, keys in final_jobs.items():
        for key in keys:
            local_file_path = os.path.normpath(os.path.join(backup_dir, key))
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
            try:
                s3.download_file(BUCKET, key, local_file_path)
            except Exception as e:
                print(f"[Master] Failed to back up {key}: {e}")
                
    print(f"[Master] Backup to {backup_dir} finished.")

def discover_and_sanitize_jobs(s3):
    print("[Master] Discovering jobs in MinIO...")
    response = s3.list_objects_v2(Bucket=BUCKET)
    
    minio_jobs = {}
    if "Contents" in response:
        for obj in response["Contents"]:
            key = obj["Key"]
            parts = key.split("/")
            if len(parts) >= 2:
                folder = parts[0]
                if folder == "backup":
                    continue
                if folder not in minio_jobs:
                    minio_jobs[folder] = []
                minio_jobs[folder].append(key)

    seen_lower = set()
    final_jobs = {}
    
    for folder, keys in minio_jobs.items():
        lower_f = folder.lower()
        unique_folder = folder
        if lower_f in seen_lower:
            unique_folder = f"{folder}_{uuid.uuid4().hex[:6]}"
            print(f"[Master] Duplicate folder name detected! Renaming {folder} -> {unique_folder}")
            
            for key in keys:
                new_key = key.replace(f"{folder}/", f"{unique_folder}/", 1)
                s3.copy_object(Bucket=BUCKET, CopySource={'Bucket': BUCKET, 'Key': key}, Key=new_key)
                s3.delete_object(Bucket=BUCKET, Key=key)
                
            final_jobs[unique_folder] = [k.replace(f"{folder}/", f"{unique_folder}/", 1) for k in keys]
        else:
            seen_lower.add(lower_f)
            final_jobs[unique_folder] = keys
            
    return final_jobs


def enqueue_jobs(q, final_jobs, failed_registry, started_registry, finished_registry):
    print(f"[Master] Checking Redis state and pushing new jobs if needed...")
    
    queued_jobs = set(q.job_ids)
    running_jobs = set(started_registry.get_job_ids())
    done_jobs = set(finished_registry.get_job_ids())
    failed_jobs = set(failed_registry.get_job_ids())
    
    known_jobs = queued_jobs.union(running_jobs, done_jobs, failed_jobs)
    
    jobs_to_queue = []
    for folder in final_jobs.keys():
        if folder not in known_jobs:
            jobs_to_queue.append(folder)
            
    print(f"[Master] Found {len(final_jobs)} total folders, {len(jobs_to_queue)} of which are new and will be queued.")
            
    for folder in jobs_to_queue:
        job_data = {"folder": folder}
        q.enqueue(
            "tasks.process_job", 
            job_data,
            job_id=folder,
            retry=Retry(max=CONFIG.get("max_retry_limit_per_video", 3)),
            result_ttl=86400
        )
        print(f"[Master] Queued job: {folder}")



def produce_queues_and_buckets():
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)
    if CONFIG.get("flush_cache_on_startup"):
        print("[Master] Flushing Redis cache as per config...")
        r.flushall()

    q = Queue(QUEUE_NAME, connection=r)
    failed_registry = FailedJobRegistry(queue=q)
    started_registry = StartedJobRegistry(QUEUE_NAME, connection=r)
    finished_registry = FinishedJobRegistry(QUEUE_NAME, connection=r)

    s3 = setup_s3_client()
    setup_code_bucket(s3)
    upload_worker_scripts(s3)

    try:
        final_jobs = discover_and_sanitize_jobs(s3)
        backup_jobs_locally(s3, final_jobs)
        enqueue_jobs(q, final_jobs, failed_registry, started_registry, finished_registry)
            
        print("[Master] Done queuing jobs.")

    except Exception as e:
        print(f"[Master] Unexpected error: {e}")


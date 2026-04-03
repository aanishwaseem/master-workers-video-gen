import sys

import collections
import collections.abc
collections.Callable = collections.abc.Callable

import os
import json
import requests
import redis
import boto3

def run_startup_checks():
    print("[Startup] Running startup checks...")
    
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(BASE_DIR, "config.json")
    CONFIG = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            CONFIG = json.load(f)

    worker_config_path = os.path.join(BASE_DIR, "worker_config.json")
    WORKER_CONFIG = {}
    if os.path.exists(worker_config_path):
        with open(worker_config_path, "r") as f:
            WORKER_CONFIG = json.load(f)

    MINIO_ENDPOINT = "http://localhost:9000"
    REDIS_HOST = "127.0.0.1"

    # 1. Local MinIO Check
    try:
        requests.get(MINIO_ENDPOINT, timeout=3)
    except requests.exceptions.RequestException:
        print(f"[ERROR] Local MinIO at {MINIO_ENDPOINT} is not reachable!")
        print("Please start up MinIO before continuing.")
        sys.exit(1)
        
    # 2. Public MinIO Check
    minio_public = CONFIG.get("minio_public")
    if minio_public:
        try:
            requests.get(minio_public, timeout=5)
        except requests.exceptions.RequestException:
            print(f"[ERROR] Public MinIO link at {minio_public} is not reachable!")
            print("Please ensure your MinIO public endpoint (e.g. ngrok/tunnels) is running and correct.")
            sys.exit(1)
            
    # 3. Local Redis Check
    try:
        r_local = redis.Redis(host=REDIS_HOST, port=6379, socket_connect_timeout=3)
        r_local.ping()
        r_local.close()
    except redis.exceptions.ConnectionError:
        print(f"[ERROR] Local Redis at {REDIS_HOST}:6379 is not reachable!")
        print("Please start up Redis before continuing.")
        sys.exit(1)
        
    # 4. Public Redis Check
    redis_public_host = CONFIG.get("redis_public_host")
    redis_public_port = CONFIG.get("redis_public_port", 6379)
    if redis_public_host:
        try:
            r_public = redis.Redis(host=redis_public_host, port=redis_public_port, socket_connect_timeout=5)
            r_public.ping()
            r_public.close()
        except redis.exceptions.ConnectionError:
            print(f"[ERROR] Public Redis at {redis_public_host}:{redis_public_port} is not reachable!")
            print("Please ensure your Redis public endpoint (e.g. ngrok/tunnels) is running and correct.")
            sys.exit(1)
            
    # 5. Check and Setup Buckets specified in worker_config.json
    worker_minio_endpoint = WORKER_CONFIG.get("minio_endpoint", "http://localhost:9000")
    worker_access_key = WORKER_CONFIG.get("minio_access_key", "minioadmin")
    worker_secret_key = WORKER_CONFIG.get("minio_secret_key", "minioadmin")

    buckets = []
    for key, value in WORKER_CONFIG.items():
        if key.endswith("_bucket") and isinstance(value, str) and value:
            buckets.append(value)

    if buckets:
        try:
            s3_client = boto3.client(
                "s3",
                endpoint_url=worker_minio_endpoint,
                aws_access_key_id=worker_access_key,
                aws_secret_access_key=worker_secret_key,
            )
            for b in buckets:
                try:
                    s3_client.head_bucket(Bucket=b)
                    print(f"[Startup] S3 Bucket '{b}' verified.")
                except Exception:
                    print(f"[Startup] S3 Bucket '{b}' not found. Creating it...")
                    try:
                        s3_client.create_bucket(Bucket=b)
                        print(f"          -> S3 Bucket '{b}' created successfully.")
                    except Exception as e:
                        print(f"[ERROR] Failed to create S3 Bucket '{b}': {e}")
                        sys.exit(1)
        except Exception as e:
            print(f"[ERROR] Failed to initialize S3 client or connect to MinIO for buckets setup: {e}")
            sys.exit(1)

    print("[Startup] All startup checks passed successfully.\n")

if __name__ == "__main__":
    run_startup_checks()

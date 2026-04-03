
import boto3
import os
import subprocess
import time
import shutil
import logging
import sys
import json
from datetime import datetime

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

MINIO_ENDPOINT = config.get('minio_endpoint')
ACCESS_KEY = config.get('minio_access_key')
SECRET_KEY = config.get('minio_secret_key')
CODE_BUCKET = config.get('minio_code_bucket')
JOBS_BUCKET = config.get('minio_jobs_bucket')
CORE_SCRIPT = config.get('worker_core_script')
FETCH_CODE = config.get('fetch_worker_code_from_minio', True)
FETCH_CONFIG = config.get('fetch_config_from_minio', False)

CONTAINER_ID = os.getenv("CONTAINER_ID", "local_instance")

# Use a safe log path depending on OS
log_dir = "/tmp" if os.name != "nt" else os.environ.get("TEMP", "C:/Temp")
os.makedirs(log_dir, exist_ok=True)
log_filename = os.path.join(log_dir, f"{CONTAINER_ID}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(sys.stdout)
    ]
)

s3 = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

def run():
    global CORE_SCRIPT, FETCH_CODE, JOBS_BUCKET
    logging.info("Starting bootstrapper...")
    if True:
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            
            if FETCH_CONFIG:
                logging.info("Fetching latest config.json from MinIO...")
                try:
                    temp_config_path = os.path.join(current_dir, 'temp_minio_config.json')
                    s3.download_file(CODE_BUCKET, 'config.json', temp_config_path)
                    
                    with open(temp_config_path, 'r') as f:
                        minio_config = json.load(f)
                        
                    # Update our local config dictionary with all matching minio values
                    config.update(minio_config)
                    
                    # Rewrite the merged config back to the local config.json file
                    with open(CONFIG_PATH, 'w') as f:
                        json.dump(config, f, indent=2)
                        
                    if os.path.exists(temp_config_path):
                        os.remove(temp_config_path)

                    CORE_SCRIPT = config.get('worker_core_script', CORE_SCRIPT)
                    FETCH_CODE = config.get('fetch_worker_code_from_minio', FETCH_CODE)
                    JOBS_BUCKET = config.get('minio_jobs_bucket', JOBS_BUCKET)
                except Exception as e:
                    logging.error(f"Failed to fetch config from MinIO: {e}. Falling back to local configuration.")

            core_path = os.path.join(current_dir, CORE_SCRIPT)

            if FETCH_CODE:
                # Ensure the bucket exists
                try:
                    s3.head_bucket(Bucket=CODE_BUCKET)
                except:
                    logging.error(f"Bucket {CODE_BUCKET} does not exist. Please create it and upload image before starting the worker.")
                    raise Exception(f"Bucket {CODE_BUCKET} does not exist. Please create it and upload image before starting the worker.")

                logging.info("Fetching latest worker code from MinIO...")

                # List all objects inside bucket with pagination
                paginator = s3.get_paginator('list_objects_v2')
                pages = paginator.paginate(Bucket=CODE_BUCKET)
                
                is_empty = True
                for page in pages:
                    if "Contents" not in page:
                        continue
                    
                    is_empty = False
                    for obj in page["Contents"]:
                        key = obj["Key"]

                        # Skip folders (MinIO may store them as zero-byte objects ending with /)
                        if key.endswith("/"):
                            continue

                        local_path = os.path.join(current_dir, key)

                        # Create local directories if they don't exist
                        os.makedirs(os.path.dirname(local_path), exist_ok=True)

                        logging.info(f"Downloading {key}...")
                        s3.download_file(CODE_BUCKET, key, local_path)

                if is_empty:
                    logging.error("Bucket is empty.")
                    raise Exception("Bucket is empty.")



            logging.info(f"Executing {CORE_SCRIPT}...")
            # This blocks until worker_core.py exits or fails
            try:
                # Capture standard output and error output into Python logger or allow them to stream naturally
                # Since we want to capture the subprocess too, piping could be used, or simply rely on
                # worker_core writing its own things to stdout which our StreamHandler sees,
                # though FileHandler might miss subprocess output unless we capture and log it.
                
                process = subprocess.Popen(["python", core_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in process.stdout:
                    logging.info(f"[worker_core] {line.rstrip()}")
                process.wait()
                
                if process.returncode != 0:
                    raise Exception(f"Worker core exited with code {process.returncode}")

            except Exception as sub_err:
                logging.error(f"Worker core execution failed: {sub_err}")
            
        except Exception as e:
            logging.error(f"Bootstrapper error: {e}. Exiting..")
            
        finally:
            if FETCH_CODE:
                logging.info("Cleaning up fetched worker code...")
                try:
                    # Remove everything that was downloaded from the bucket
                    paginator = s3.get_paginator('list_objects_v2')
                    pages = paginator.paginate(Bucket=CODE_BUCKET)
                    
                    # We need to collect the keys first to avoid deleting directories before their files
                    downloaded_keys = []
                    for page in pages:
                        if "Contents" in page:
                            for obj in page["Contents"]:
                                downloaded_keys.append(obj["Key"])
                                
                    # Delete files
                    for key in downloaded_keys:
                        if not key.endswith("/"):
                            file_path = os.path.join(current_dir, key)
                            if os.path.exists(file_path):
                                try:
                                    os.remove(file_path)
                                except OSError:
                                    pass
                    
                    # Try to remove empty directories that were created
                    # Sort descending by length so deep directories are removed before parent directories
                    downloaded_keys.sort(key=len, reverse=True)
                    for key in downloaded_keys:
                        dir_path = os.path.join(current_dir, os.path.dirname(key))
                        if os.path.exists(dir_path) and dir_path != current_dir:
                            try:
                                os.rmdir(dir_path)
                            except OSError:
                                pass # Directory not empty or just unable to remove
                                
                    logging.info("Cleanup complete.")
                except Exception as cleanup_err:
                    logging.error(f"Failed to clean up some downloaded files: {cleanup_err}")
                
            # Auto-destruction logic
            container_id = os.environ.get("CONTAINER_ID")
            api_key = os.environ.get("CONTAINER_API_KEY")

            if container_id and api_key:
                logging.info("Task complete. Sending destroy command to Vast.ai...")
                print("Task complete. Sending destroy command to Vast.ai...")
                try:
                    subprocess.run([
                        "vastai", "destroy", "instance", 
                        container_id, "--api-key", api_key
                    ], check=True)
                except Exception as e:
                    logging.error(f"Failed to auto-destroy: {e}")
                    print(f"Failed to auto-destroy: {e}")
                    pass
            else:
                logging.warning("Missing Vast.ai credentials. Manual destruction required.")

if __name__ == "__main__":
    run()

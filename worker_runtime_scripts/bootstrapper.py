
import collections
import collections.abc
collections.Callable = collections.abc.Callable
import boto3

import os
import subprocess
import time
import shutil
import logging
import sys
import json
from datetime import datetime

def get_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

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

def run():
    logging.info("Starting bootstrapper...")
    
    config = get_config()
    code_bucket = config.get('minio_code_bucket')
    core_script = config.get('worker_core_script')
    fetch_code = config.get('fetch_worker_code_from_minio', True)
    fetch_config = config.get('fetch_config_from_minio', False)

    s3 = boto3.client(
        "s3",
        endpoint_url=config.get('minio_endpoint'),
        aws_access_key_id=config.get('minio_access_key'),
        aws_secret_access_key=config.get('minio_secret_key'),
    )

    if True:
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            
            if fetch_config:
                logging.info("Fetching latest config.json from MinIO...")
                try:
                    temp_config_path = os.path.join(current_dir, 'temp_minio_config.json')
                    s3.download_file(code_bucket, 'config.json', temp_config_path)
                    
                    with open(temp_config_path, 'r') as f:
                        minio_config = json.load(f)
                        
                    # Update our local config dictionary with all matching minio values
                    config.update(minio_config)
                    
                    # Rewrite the merged config back to the local config.json file
                    config_path = os.path.join(current_dir, 'config.json')
                    with open(config_path, 'w') as f:
                        json.dump(config, f, indent=2)
                        
                    if os.path.exists(temp_config_path):
                        os.remove(temp_config_path)

                    core_script = config.get('worker_core_script', core_script)
                    fetch_code = config.get('fetch_worker_code_from_minio', fetch_code)
                    code_bucket = config.get('minio_code_bucket', code_bucket)
                    
                    # Re-initialize S3 in case credentials or endpoint changed
                    s3 = boto3.client(
                        "s3",
                        endpoint_url=config.get('minio_endpoint'),
                        aws_access_key_id=config.get('minio_access_key'),
                        aws_secret_access_key=config.get('minio_secret_key'),
                    )
                except Exception as e:
                    logging.error(f"Failed to fetch config from MinIO: {e}. Falling back to local configuration.")

            core_path = os.path.join(current_dir, core_script)

            if fetch_code:
                # Ensure the bucket exists
                try:
                    s3.head_bucket(Bucket=code_bucket)
                except:
                    logging.error(f"Bucket {code_bucket} does not exist. Please create it and upload image before starting the worker.")
                    raise Exception(f"Bucket {code_bucket} does not exist. Please create it and upload image before starting the worker.")

                logging.info("Fetching latest worker code from MinIO...")

                # List all objects inside bucket with pagination
                paginator = s3.get_paginator('list_objects_v2')
                pages = paginator.paginate(Bucket=code_bucket)
                
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
                        s3.download_file(code_bucket, key, local_path)

                if is_empty:
                    logging.error("Bucket is empty.")
                    raise Exception("Bucket is empty.")



            logging.info(f"Executing {core_script}...")
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
            if fetch_code:
                logging.info("Cleaning up fetched worker code...")
                try:
                    # Remove everything that was downloaded from the bucket
                    paginator = s3.get_paginator('list_objects_v2')
                    pages = paginator.paginate(Bucket=code_bucket)
                    
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

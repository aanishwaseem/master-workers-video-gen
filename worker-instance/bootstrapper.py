
import sys
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
from datetime import datetime

MINIO_ENDPOINT = "https://unfunereal-unconvertibly-tresa.ngrok-free.dev/"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"
CODE_BUCKET = "worker-code"
JOBS_BUCKET = "jobs"
CORE_SCRIPT = "worker_core.py"

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
    logging.info("Starting bootstrapper...")
    if True:
        try:
            # Ensure the bucket exists
            try:
                s3.head_bucket(Bucket=CODE_BUCKET)
            except:
                logging.error(f"Bucket {CODE_BUCKET} does not exist. Please create it and upload image before starting the worker.")
                raise Exception(f"Bucket {CODE_BUCKET} does not exist. Please create it and upload image before starting the worker.")

            logging.info("Fetching latest worker code from MinIO...")

            current_dir = os.path.dirname(os.path.abspath(__file__))

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



            core_path = os.path.join(current_dir, CORE_SCRIPT)

            logging.info(f"Executing {CORE_SCRIPT}...")
            # This blocks until worker_core.py exits or fails
            try:
                # Ensure JOBS_BUCKET exists
                try:
                    s3.head_bucket(Bucket=JOBS_BUCKET)
                except:
                    logging.info(f"Bucket {JOBS_BUCKET} does not exist, attempting to create it...")
                    s3.create_bucket(Bucket=JOBS_BUCKET)

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

                # Success flag
                container_id = os.environ.get("CONTAINER_ID", "local_instance")
                
                try:
                    s3.upload_file(log_filename, JOBS_BUCKET, f"{container_id}/worker.log")
                except Exception as log_err:
                    logging.error(f"Failed to upload log file: {log_err}")
                    
                s3.put_object(
                    Bucket=JOBS_BUCKET,
                    Key=f"{container_id}/done.flag", 
                    Body="done"
                )
            except Exception as sub_err:
                logging.error(f"Worker core execution failed: {sub_err}")
                container_id = os.environ.get("CONTAINER_ID", "local_instance")
                
                try:
                    s3.upload_file(log_filename, JOBS_BUCKET, f"{container_id}/worker.log")
                except:
                    pass
                    
                s3.put_object(
                    Bucket=JOBS_BUCKET,
                    Key=f"{container_id}/done.flag", 
                    Body="failed"
                )
            
        except Exception as e:
            logging.error(f"Bootstrapper error: {e}. Exiting..")
            try:
                # Setup JOBS bucket as fallback if it crashed before main loop
                try:
                    s3.head_bucket(Bucket=JOBS_BUCKET)
                except:
                    s3.create_bucket(Bucket=JOBS_BUCKET)
                    
                container_id = os.environ.get("CONTAINER_ID", "local_instance")
                
                try:
                    s3.upload_file(log_filename, JOBS_BUCKET, f"{container_id}/worker.log")
                except:
                    pass
                    
                s3.put_object(
                    Bucket=JOBS_BUCKET,
                    Key=f"{container_id}/done.flag", 
                    Body="failed"
                )
            except:
                pass
            
        finally:
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
                
        # print("Restarting worker core in 5 seconds...")
        # time.sleep(5)

if __name__ == "__main__":
    run()

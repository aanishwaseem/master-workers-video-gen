
import boto3
import os
import subprocess
import time

MINIO_ENDPOINT = "http://localhost:9000"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"
CODE_BUCKET = "worker-code"
CORE_SCRIPT = "worker_core.py"

s3 = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

def run():
    print("Starting bootstrapper...")
    if True:
        try:
            # Ensure the bucket exists
            try:
                s3.head_bucket(Bucket=CODE_BUCKET)
            except:
                # print(f"Waiting for bucket {CODE_BUCKET} to be created...")
                # time.sleep(5)
                # # continue
                raise Exception(f"Bucket {CODE_BUCKET} does not exist. Please create it and upload image before starting the worker.")

            print("Fetching latest image from MinIO...")
            current_dir = os.path.dirname(os.path.abspath(__file__))
            dest = os.path.join(current_dir, CORE_SCRIPT)
            s3.download_file(CODE_BUCKET, CORE_SCRIPT, dest)
            s3.download_file(CODE_BUCKET, "tasks.py", dest)

            
            print(f"Executing {CORE_SCRIPT}...")
            # This blocks until worker_core.py exits or fails
            subprocess.run(["python", dest])
            
        except Exception as e:
            print(f"Bootstrapper error: {e}. Exiting..")
        
        # print("Restarting worker core in 5 seconds...")
        # time.sleep(5)

if __name__ == "__main__":
    run()

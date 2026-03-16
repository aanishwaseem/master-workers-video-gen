import boto3
import os
import subprocess
import time

MINIO_ENDPOINT = "http://192.168.100.5:9000"
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
    while True:
        try:
            # Ensure the bucket exists
            try:
                s3.head_bucket(Bucket=CODE_BUCKET)
            except:
                print(f"Waiting for bucket {CODE_BUCKET} to be created...")
                time.sleep(5)
                continue

            print("Fetching latest worker_core.py from MinIO...")
            os.makedirs("core", exist_ok=True)
            dest = os.path.join("core", CORE_SCRIPT)
            s3.download_file(CODE_BUCKET, CORE_SCRIPT, dest)
            
            print(f"Executing {CORE_SCRIPT}...")
            # This blocks until worker_core.py exits or fails
            subprocess.run(["python", dest])
            
        except Exception as e:
            print(f"Bootstrapper error: {e}")
        
        print("Restarting worker core in 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    run()

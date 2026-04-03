import sys
import collections
import collections.abc
collections.Callable = collections.abc.Callable

from vastai_sdk import VastAI
import json
import boto3
import time
import os
import redis
from rq import Queue
from startup_checks import run_startup_checks

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load master config to get vastai properties
config_path = os.path.join(BASE_DIR, "config.json")
MASTER_CONFIG = {}
if os.path.exists(config_path):
    with open(config_path, "r") as f:
        MASTER_CONFIG = json.load(f)

worker_config_path = os.path.join(BASE_DIR, "worker_config.json")
WORKER_CONFIG = {}
if os.path.exists(worker_config_path):
    with open(worker_config_path, "r") as f:
        WORKER_CONFIG = json.load(f)

API_KEY = MASTER_CONFIG.get("vastai_api_key", "c55e7735e11d4cbab86bd25ff9825af42289a4409f5377ac49393ea504307cc4")
sdk = VastAI(api_key=API_KEY)
FULL_IMAGE_PATH = MASTER_CONFIG.get("docker_image_path", "burnerspam/vast-worker-instance:latest") # Update this

# MinIO credentials for matching up with the worker bootstrapper signals
MINIO_ENDPOINT = WORKER_CONFIG.get("minio_endpoint", "https://unfunereal-unconvertibly-tresa.ngrok-free.dev/")
ACCESS_KEY = WORKER_CONFIG.get("minio_access_key", "minioadmin")
SECRET_KEY = WORKER_CONFIG.get("minio_secret_key", "minioadmin")
CODE_BUCKET = WORKER_CONFIG.get("minio_code_bucket", "worker-code")
JOBS_BUCKET = WORKER_CONFIG.get("minio_jobs_bucket", "jobs")

s3 = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

class InstanceManager:
    def __init__(self):
        self.sdk = sdk

    def stop(self, instance_id: int):
        try:
            print(f"[InstanceManager] Stopping instance {instance_id}...")
            self.sdk.stop_instance(id=instance_id)
            print("[InstanceManager] ✅ Instance stopped.")
        except Exception as e:
            print(f"[InstanceManager] ❌ Stop failed: {e}")

    def destroy(self, instance_id: int):
        try:
            print(f"[InstanceManager] Destroying instance {instance_id}...")
            self.sdk.destroy_instance(id=instance_id)
            print("[InstanceManager] 🔥 Instance destroyed.")
        except Exception as e:
            print(f"[InstanceManager] ❌ Destroy failed: {e}")

    def restart(self, instance_id: int):
        try:
            print(f"[InstanceManager] Restarting instance {instance_id}...")
            self.sdk.start_instance(id=instance_id)
            print("[InstanceManager] 🚀 Instance restarted.")
        except Exception as e:
            print(f"[InstanceManager] ❌ Restart failed: {e}")


def wait_for_completion(instance_id):
    print(f"Waiting for worker instance {instance_id} to drop its status flag...")
    while True:
        try:
            flag_key = f"{instance_id}/done.flag"
            response = s3.get_object(Bucket=JOBS_BUCKET, Key=flag_key)
            status = response['Body'].read().decode('utf-8').strip()
            print(f"Worker {instance_id} finished with status: {status}")
            return status
        except Exception:
            time.sleep(15)


def display_stats(status_list):
    completed = status_list.count("done")
    failed = status_list.count("failed")
    print(f"\n===== INSTANCE EXECUTION STATS =====")
    print(f"Total monitored: {len(status_list)}")
    print(f"✅ Completed:    {completed}")
    print(f"❌ Failed:       {failed}")
    print(f"====================================")


def main():
    print("Running startup checks...")
    run_startup_checks()
    
    print("Checking initial configurations...")
    
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
        q = Queue("video_jobs", connection=r)
        queue_count = len(q.job_ids)
        print(f"\n======================================")
        print(f"📊 JOBS CURRENTLY IN QUEUE: {queue_count}")
        print(f"======================================\n")
    except Exception as e:
        print(f"⚠️ Could not fetch queue count from Redis: {e}")
    
    # Load master config to check if we should update workers config
    if MASTER_CONFIG.get("update_workers_config", False):
        if os.path.exists("worker_config.json"):
            print("Uploading worker_config.json to MinIO as config.json...")
            s3.upload_file("worker_config.json", CODE_BUCKET, "config.json")
            print("Done uploading worker config.")

    print("Searching for instances...")
    offers = sdk.search_offers(query="gpu_name==GTX_1070 num_gpus==1", order="price")
    
    if not offers:
        print("No instances found matching your criteria.")
        return

    manager = InstanceManager()
    launched_instances = []

    for offer in offers:
        offer_id = offer.get('id')
        gpu_name = offer.get('gpu_name', 'Unknown')
        num_gpus = offer.get('num_gpus', 1)
        price_hr = offer.get('dph_total', offer.get('dph_base', offer.get('price', 'Unknown')))
        ram = offer.get('sys_ram', 'Unknown')
        reliability = offer.get('reliability2', 'Unknown')
        
        print(f"\n===== INSTANCE SPECS =====")
        print(f"ID:          {offer_id}")
        print(f"GPU:         {num_gpus}x {gpu_name}")
        print(f"Price:       ${price_hr}/hr")
        print(f"System RAM:  {ram} GB")
        print(f"Reliability: {reliability}%")
        print(f"==========================")
        
        user_input = input("Do you want to launch this instance? (y = yes / n = next / q = quit): ").strip().lower()
        
        if user_input == 'y':
            gpu_name_formatted = gpu_name.replace(" ", "_")
            print(f"\nLaunching instance with image: {FULL_IMAGE_PATH}...")
            
            # The SDK often returns a dict/JSON with the response, we need to extract the new contract ID
            # the machine's actual "instance_id" will be returned

            response = dict(sdk.launch_instance(
                id=offer_id, 
                image=f"{FULL_IMAGE_PATH}",
                disk=15,
                env="-p 8081:8081/udp -h billybob",
                gpu_name=gpu_name_formatted,
                num_gpus='1',
                ssh=True,
                direct=True,
                onstart_cmd="env | grep _ >> /etc/environment; echo 'starting up'",
                launch_mode="ssh"
            ))
            print(f"Launch Response: {response}")
            
            # Identify the new machine instance ID, which vast returns as 'new_contract' 
            new_instance_id = response.get('new_contract', offer_id) 
            print(f"🚀 Instance successfully launched! Assigned Instance ID: {new_instance_id}")
            
            launched_instances.append(new_instance_id)
            
            # Option to continue launching more or stop
            more = input("Do you want to launch MORE instances? (y/n): ").strip().lower()
            if more != 'y':
                break
                
        elif user_input == 'q':
            print("Quitting setup.")
            break
        else:
            print("Skipping to the next best offer...\n")
    else:
        print("You've reviewed all available offers.")


if __name__ == "__main__":
    main()

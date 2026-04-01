from vastai_sdk import VastAI
import json
import boto3
import time
import os

API_KEY = "b289c7ae41a8ae03381ccb5fa529b02bf5b5a47616fea98477fa52d20dab53d2"
sdk = VastAI(api_key=API_KEY)
FULL_IMAGE_PATH = "burnerspam/vast-worker-instance:latest" # Update this

# Hardcoded MinIO credentials for matching up with the worker bootstrapper signals
MINIO_ENDPOINT = "https://unfunereal-unconvertibly-tresa.ngrok-free.dev/"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"
CODE_BUCKET = "worker-code"
JOBS_BUCKET = "jobs"

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
                image=FULL_IMAGE_PATH,
                gpu_name=gpu_name_formatted, 
                num_gpus='1',
                disk=10,
                env="-e CONTAINER_ID={VAST_CONTAINERLABEL}" # We can't interpolate Vast label until container starts, but ideally the instance ID itself is used. Let's force an env var if possible, otherwise rely on ID returned. Instead we'll track what the API returns.
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

    # If we launched machines, wait for them
    if launched_instances:
        print(f"\nWait cycle initiated for {len(launched_instances)} instances...")
        final_statuses = []
        
        # NOTE: wait_for_completion blocks heavily. If running multiple, it waits for them sequentially.
        # So we wait for the first, then the second... which is fine since they will eventually both finish.
        for inst_id in launched_instances:
            # We assume CONTAINER_ID on worker matches the `inst_id`. In a real system,
            # you might pass `-e CONTAINER_ID={inst_id}` in launch_instance parameters.
            
            # Optional: You can try injecting the container ID via the Env parameter during launch above
            # env=f"-e CONTAINER_ID={inst_id}"
            
            status = wait_for_completion(inst_id)
            final_statuses.append(status)
            
            # Auto cleanup
            manager.stop(inst_id)
            
        display_stats(final_statuses)

if __name__ == "__main__":
    main()

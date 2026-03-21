from datetime import datetime
import os
import json
import boto3
import sys

# MinIO config
MINIO_ENDPOINT = "http://localhost:9000"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"
INPUT_BUCKET = "videos-input"

s3 = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def push_to_minio(temp_folder, config_name, video_name):
    """Recursively upload a folder to MinIO buckets under config/video path"""
    for root, dirs, files in os.walk(temp_folder):
        for file in files:
            local_path = os.path.join(root, file)
            # Create a relative path from the temp folder root
            relative_path = os.path.relpath(local_path, temp_folder)
            
            # The S3 key pattern will be: config_name/video_name/relative_path
            s3_key = f"{video_name}/{relative_path}".replace("\\", "/")
            
            try:
                log(f"Uploading {local_path} -> {s3_key}")
                s3.upload_file(local_path, INPUT_BUCKET, s3_key)
            except Exception as e:
                log(f"Failed to upload {local_path}: {e}")

def farm_batch(batch_input_folder, config_name):
    """
    Simulated batch processing. 
    Instead of moving to local Mats Output, it uploads to MinIO.
    """
    log(f"Farming batch for config {config_name} in {batch_input_folder}...")
    
    # Iterate through assumed "Story folders" in the batch input
    for item in os.listdir(batch_input_folder):
        item_path = os.path.join(batch_input_folder, item)
        if os.path.isdir(item_path):
            video_name = item
            log(f"Processing Video: {video_name}")
            
            # Pretend this generates the materials...
            
            # Once materials are in the temp_folder (in this case, item_path itself for simulation)
            push_to_minio(item_path, config_name, video_name)
            
    log("Batch processed.")

if __name__ == "__main__":
    log("Starting Producer (mats_farmer)...")
    
    # Ensure bucket exists
    try:
        s3.head_bucket(Bucket=INPUT_BUCKET)
    except Exception:
        log(f"Bucket {INPUT_BUCKET} not found. Creating...")
        s3.create_bucket(Bucket=INPUT_BUCKET)

    # Simulated run
    farmer_input = os.path.join(BASE_DIR, "sample_input")
    
    if False:
        os.makedirs(farmer_input)
        log(f"Created dummy input dir: {farmer_input}. Place folders here to test.")
    else:
        farm_batch(farmer_input, "config_1")

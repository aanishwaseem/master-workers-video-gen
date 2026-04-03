import sys
import os
import boto3
import uuid
import shutil
import json

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

# ================= GLOBAL CONFIG =================
MINIO_ENDPOINT = config.get('minio_endpoint')
ACCESS_KEY = config.get('minio_access_key')
SECRET_KEY = config.get('minio_secret_key')
INPUT_BUCKET = config.get('minio_input_bucket')
OUTPUT_BUCKET = config.get('minio_output_bucket')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_GEN_DIR = os.path.join(BASE_DIR, config.get('video_gen_dir_name'))

# Setup import for main.py
original_dir = os.getcwd()
os.chdir(VIDEO_GEN_DIR)
sys.path.append(VIDEO_GEN_DIR)

try:
    import main
except ImportError as e:
    print(f"Failed to import main: {e}")

os.chdir(original_dir)

def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )

def download_from_minio(folder, dest_dir):
    s3 = get_s3_client()
    folder_input_path = os.path.join(dest_dir, folder)
    os.makedirs(folder_input_path, exist_ok=True)
    
    print(f"[tasks] Downloading {folder} from MinIO to {folder_input_path}...")
    prefix = f"{folder}/"
    response = s3.list_objects_v2(Bucket=INPUT_BUCKET, Prefix=prefix)
    
    if "Contents" not in response:
        raise Exception(f"No files found for job {folder}")

    for obj in response["Contents"]:
        key = obj["Key"]
        relative_key = key[len(prefix):]
        if relative_key == "":
            continue
            
        dest = os.path.join(folder_input_path, relative_key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        s3.download_file(INPUT_BUCKET, key, dest)
        
    print(f"[tasks] Download Complete: {folder}")

def upload_to_minio(folder, source_dir):
    s3 = get_s3_client()
    
    mp4_files = [f for f in os.listdir(source_dir) if f.endswith(".mp4")]
    
    if not mp4_files:
        raise Exception(f"No .mp4 files resulted from the generation of {folder}")
        
    print(f"[tasks] Uploading MP4s for {folder} from {source_dir}...")
    for mp4_file in mp4_files:
        local_file = os.path.join(source_dir, mp4_file)
        s3_key = f"{folder}/{mp4_file}"
        s3.upload_file(local_file, OUTPUT_BUCKET, s3_key)
        print(f"[tasks] Upload Complete: {s3_key}")

def safe_process_project(project_name, project_path, output_root):
    try:
        print(f"[{project_name}] Starting processing...")
        success = main.process_project(project_name, project_path, output_root)
        return success
    except Exception as e:
        print(f"[{project_name}] Exception caught during processing: {e}")
        return False

def process_job(job_data):
    """
    This is the core task function that WindowsWorker will execute in a clean spawned process.
    """
    folder = job_data["folder"]
    print(f"\n========== STARTING VIDEO RENDER: {folder} ==========")
    
    random_id = uuid.uuid4().hex[:8]
    input_dir = os.path.join(original_dir, f"input_{random_id}")
    output_dir = os.path.join(original_dir, f"output_{random_id}")
    
    try:
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        
        # 1. Download
        download_from_minio(folder, input_dir)
        
        # 2. Process
        project_path = os.path.join(input_dir, folder)
        
        os.chdir(VIDEO_GEN_DIR)
        success = safe_process_project(folder, project_path, output_dir)
        
        if not success:
            raise RuntimeError("safe_process_project returned False")
            
        # 3. Upload Results
        os.chdir(original_dir)
        upload_to_minio(folder, output_dir)
        
        print(f"========== COMPLETED: {folder} ==========\n")
        return True
        
    except Exception as e:
        print(f"========== FAILED: {folder} ==========")
        print(f"Error: {e}")
        raise e
        
    finally:
        os.chdir(original_dir)
        # 4. Clean up temp random folders
        for d in [input_dir, output_dir]:
            if os.path.exists(d):
                try:
                    shutil.rmtree(d)
                    print(f"[Cleanup] Deleted temp directory: {d}")
                except Exception as rm_exc:
                    print(f"[Cleanup] Warning: Could not delete {d} - {rm_exc}")
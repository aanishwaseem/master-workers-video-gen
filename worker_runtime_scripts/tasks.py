import os
import subprocess
import boto3

# ================= GLOBAL CONFIG =================
MINIO_ENDPOINT = "https://unfunereal-unconvertibly-tresa.ngrok-free.dev/"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"
INPUT_BUCKET = "videos-input"
OUTPUT_BUCKET = "videos-output"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_GEN_DIR = os.path.join(BASE_DIR, "video-gen")
INPUT_FILES_DIR = os.path.join(VIDEO_GEN_DIR, "input_files")
OUTPUT_FILES_DIR = os.path.join(VIDEO_GEN_DIR, "output_files")
VIDEO_GENERATION_SCRIPT = "video_generation_script.py"

os.makedirs(INPUT_FILES_DIR, exist_ok=True)
os.makedirs(OUTPUT_FILES_DIR, exist_ok=True)

def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )

def download_from_minio(folder):
    s3 = get_s3_client()
    folder_input_path = os.path.join(INPUT_FILES_DIR, folder)
    os.makedirs(folder_input_path, exist_ok=True)
    
    print(f"[tasks] Downloading {folder} from MinIO...")
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

def upload_to_minio(folder):
    s3 = get_s3_client()
    folder_output_path = os.path.join(OUTPUT_FILES_DIR, folder)
    
    if not os.path.exists(folder_output_path):
        raise Exception(f"Result folder not found: {folder_output_path}")
        
    mp4_files = [f for f in os.listdir(folder_output_path) if f.endswith(".mp4")]
    
    if not mp4_files:
        raise Exception(f"No .mp4 files resulted from the generation of {folder}")
        
    print(f"[tasks] Uploading MP4s for {folder}...")
    for mp4_file in mp4_files:
        local_file = os.path.join(folder_output_path, mp4_file)
        s3_key = f"{folder}/{mp4_file}"
        s3.upload_file(local_file, OUTPUT_BUCKET, s3_key)
        print(f"[tasks] Upload Complete: {s3_key}")

def process_job(job_data):
    """
    This is the core task function that WindowsWorker will execute in a clean spawned process.
    """
    folder = job_data["folder"]
    print(f"\n========== STARTING VIDEO RENDER: {folder} ==========")
    
    try:
        # 1. Download
        download_from_minio(folder)
        
        # 2. Process
        print(f"[tasks] Running video generation script...")
        script_path = os.path.join(VIDEO_GEN_DIR, VIDEO_GENERATION_SCRIPT)
        
        job_local_path = os.path.join(INPUT_FILES_DIR, folder)

        # Block the worker until finished
        process = subprocess.run(
            ["python", script_path, job_local_path],
            cwd=VIDEO_GEN_DIR, # Let it run inside video-gen natively
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # Stream the output so it shows in worker console/logs
        print(process.stdout)
        
        if process.returncode != 0:
            raise Exception(f"Subprocess failed with exit code: {process.returncode}")
            
        # 3. Upload Results
        upload_to_minio(folder)
        
        print(f"========== COMPLETED: {folder} ==========\n")
        return True
        
    except Exception as e:
        print(f"========== FAILED: {folder} ==========")
        print(f"Error: {e}")
        raise e  # Ensures RQ marks the job as Failed in the FailedJobRegistry!
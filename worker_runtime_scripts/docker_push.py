import subprocess
import os

# --- SETTINGS ---
DOCKER_USER = "burnerspam"
IMAGE_NAME = "vast-worker-instance"
TAG = "latest"
FULL_IMAGE_PATH = f"{DOCKER_USER}/{IMAGE_NAME}:{TAG}"

def build_and_push():
    # 1. Login (Only needs to be done once, but safe to keep)
    print("Authenticating with Docker Hub...")
    subprocess.run("docker login", shell=True, check=True)

    # 2. Build the image using the Dockerfile in your current directory
    print(f"Building image {FULL_IMAGE_PATH}...")
    subprocess.run(f"docker build -t {FULL_IMAGE_PATH} .", shell=True, check=True)

    # 3. Push to Docker Hub
    print(f"Pushing {FULL_IMAGE_PATH} to cloud...")
    subprocess.run(f"docker push {FULL_IMAGE_PATH}", shell=True, check=True)
    
    print("\n✅ Success! Your image is now on Docker Hub.")
    print(f"You can now use '{FULL_IMAGE_PATH}' as the image name in Vast.ai.")

if __name__ == "__main__":
    build_and_push()

# Distributed Video Rendering Workers

- **Input:** video materials (per-job folder: scripts, audio, images, etc.)
- **Output:** final renders (MP4 files)
- **Goal:** **speed up rendering** by running many workers in parallel **while keeping each render atomic** (a job either finishes and uploads its results, or it fails and is retried).

### INPUT: VIDEO MATERIALS
You upload each job as a **folder** under the MinIO bucket:

- `videos-input/<job_folder_name>/...files...`

The job folder name becomes the **job id**.

### OUTPUT: FINAL RENDERS
Workers upload completed MP4s to:

- `videos-output/<job_folder_name>/<some_name>.mp4`

---

## Key features

### 1) Shared memory (shared storage)
MinIO is used as S3-compatible shared storage so:

- the **master** can discover new jobs by listing the input bucket
- **workers** can download the exact same inputs no matter which machine picks the job
- outputs are uploaded to a shared output bucket
- worker code (py files or docker image) is published by the master to a dedicated MinIO bucket so instances can self-update

Buckets used by default:

- `videos-input` — input job folders (materials)
- `videos-output` — final renders
- `worker-code` — worker runtime scripts distributed to worker instances

### 2) Dashboard for queue monitoring

- `rq-dashboard` (third-party) can be used to view queued/started/failed jobs
- the master also prints job state transitions in the console

---

### Flow
1. You upload a new folder into `videos-input`.
2. `master.py` detects the new folder and enqueues a job into Redis/RQ using the folder name as the job id.
3. A worker takes the job and runs `tasks.process_job()`:
   - downloads the input folder from MinIO to local disk
   - runs the rendering function from video_gen module
   - if successful, uploads the resulting MP4(s) to MinIO output bucket
4. Completion/failure is recorded in RQ registries (Queued / Started / Finished / Failed), visible to the dashboard.

---

## Deliverable folders

### Root
- `master.py` — master process that discovers jobs in MinIO and enqueues them into Redis.

### Worker runtime
There are two copies of worker runtime code:

- `worker/` — the “source” scripts the master uploads to MinIO (`worker-code` bucket)

Which contain:

- `worker_core.py` — RQ worker loop (Windows compatible)
- `tasks.py` — the job implementation (download from Shared storage -> Run the video-gen's function -> Upload to Shared storage)
- `video-gen/` — the actual rendering script module

---

## Functions

### `master.py`
**Purpose:**
- Poll MinIO input bucket for new job folders.
- Enqueue unseen folders into Redis/RQ.
- Upload latest worker runtime scripts into MinIO (`worker-code` bucket).
- Print job status transitions using queue registries.

**Key behaviors & definitions:**

- Main loop (`while True`)
  - Lists objects in `videos-input` and infers folder names as job ids.
  - Reads RQ registries:
    - queued: `q.job_ids`
    - running: `StartedJobRegistry`
    - finished: `FinishedJobRegistry`
    - failed: `FailedJobRegistry`
  - Enqueues new jobs via:
    - `q.enqueue("tasks.process_job", job_data, job_id=folder, retry=Retry(max=...))`
  - Sleeps 5 seconds between iterations.

**Atomicity note:**
- The master sets `job_id=folder`, so each job folder is only enqueued once (unless removed from registries).

---

### `worker/bootstrapper.py`
**Purpose:**
- “Self-updating” worker launcher.
- Fetches the latest `worker_core.py` (and any other objects) from MinIO bucket `worker-code` into the local `worker-instance/` directory.
- Starts `worker_core.py`.
- In short, a worker instance only has to run this file.

**Key definitions:**

- `run()`
  - Checks `worker-code` bucket exists.
  - Downloads all objects in the bucket to the local instance folder.
  - Executes the downloaded `worker_core.py` via `subprocess.run(["python", core_path])`.

### `pyworker/worker_core.py`)
**Purpose:**
- Runs an RQ worker compatible with Windows process semantics.
- Pulls jobs from Redis queue `video_jobs` and executes `tasks.process_job` in a spawned process.

**Key definitions:**

- `class NoOpDeathPenalty`
  - **What it does:** a dummy context manager.
  - **Why:** RQ’s normal “death penalty” relies on Unix signals; Windows `spawn` workers don’t support it reliably.

- `start_worker()`
  - Creates Redis connection.
  - Creates an RQ `Queue`.
  - Creates an RQ `SimpleWorker` for that queue.
  - Sets `worker.death_penalty_class = NoOpDeathPenalty`.
  - Calls `worker.work()` to start consuming jobs.

- `MAIN` block
  - Loads optional config from `video-gen/config.json`:
    - reads `no_of_concurrent_generations` into `MAX_CONCURRENCY`
    - Spawns n workers. Each worker performs job described in tasks.py

---

### `worker/tasks.py`
**Purpose:**
- Implements the atomic “download → render → upload” job.

**Key definitions:**

- `get_s3_client()`
  - Returns a boto3 S3 client configured for MinIO.

- `download_from_minio(folder)`
  - Downloads every object under `videos-input/<folder>/...` into local:
    - `video-gen/input_files/<folder>/...`

- `upload_to_minio(folder)`
  - Looks in local:
    - `video-gen/output_files/<folder>/`
  - Uploads all `.mp4` files to:
    - `videos-output/<folder>/<mp4_name>`
  - Errors if folder doesn’t exist or has no `.mp4`.

- `process_job(job_data)`
  - Expects `job_data["folder"]`.
  - Runs:
    1) `download_from_minio(folder)`
    2) `Call a function imported from module video-gen`
    3) `upload_to_minio(folder)` **only if the subprocess succeeded**
  - Raises exceptions on failure so RQ marks the job failed (and retry logic can apply).

**Atomicity guarantee (current):**
- Upload doesn’t happen unless the render subprocess returns exit code 0.

---

## Configuration knobs

### Root `config.json`
- `max_retry_limit_per_video`
  - Used by the master to set RQ retries for each job.
- `burst_worker_when_inactive`
  - If true, Worker can stop if queue is empty.

## Notes on speeding up rendering

You speed up the system by:

- running more worker machines

The current code is already safe for parallelism across workers because the job id is the folder name and output upload is performed only when the render succeeds.

---

## What the system expects from the `video-gen` module

The master/worker system treats each MinIO input folder as **one atomic unit of work**.
So the video-gen layer must be able to render **one project** given a local folder path.

### Required callable: `process_project(project_name, project_path, output_root)`

In `video gen/main2.py`, the worker expects a renderer shaped like:

- `process_project(project_name, project_path, output_root) -> bool`
  - **project_name**: the job id / folder name
  - **project_path**: path to the local inputs for this job (downloaded from MinIO)
  - **output_root**: directory where the final result should be written
  - **output contract**: must produce an MP4 at `os.path.join(output_root, f"{project_name}.mp4")`
  - **return value**: `True` on success; `False` or raise an exception on failure

Why this contract exists:

- The worker core spawns clean processes and needs a **single entrypoint** per job.
- RQ retries require failure to be detectable (exception or `False`).

### Atomicity expectation at renderer level

- Render to a temporary filename first.
- On success, rename/move into the final output filename.
- The worker uploads to MinIO **only after** the renderer succeeds.

---

## Windows vs Cloud packaging

### Windows

- Workers expect Python **`.py` files** on disk.
- `master.py` uploads the latest `worker_core.py` (and optionally `tasks.py`) into MinIO bucket `worker-code`.
- `worker/bootstrapper.py` downloads those files and executes `worker_core.py`.
- The video-gen renderer runs as local Python code/subprocess.

### Cloud (target)

For cloud, workers should be shipped as a **Docker image**, especially because `video-gen` has heavy native deps.

The worker Docker image should contain:

- `worker/` (worker core + tasks)
- the production `video-gen` module (renderer)
- FFmpeg on Linux
- GPU acceleration stack (NVIDIA), plus Vulkan/libplacebo where used

---

# Use an official Python runtime as a parent image
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

# Non-interactive installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
# - python3, pip
# - ffmpeg (basic)
# - chromedriver/chrome (REMOVED - Not used)
# - xvfb (for headless display)
# - libsm6, libxext6 (opencv deps)
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    python3.11-venv \
    python3.11-dev \
    ffmpeg \
    git \
    wget \
    curl \
    gnupg \
    unzip \
    xvfb \
    libsm6 \
    libxext6 \
    libgl1-mesa-glx \
    libvulkan1 \
    mesa-vulkan-drivers \
    vulkan-tools \
    && rm -rf /var/lib/apt/lists/*

# Alias python to python3.11
RUN ln -sf /usr/bin/python3.11 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

WORKDIR /app

# Upgrade pip
RUN python -m pip install --no-cache-dir --upgrade pip

# Copy the SANITIZED requirements file
COPY requirements_docker.txt .

# Install Dependencies
# REMOVED: PyTorch extra index url since we removed torch dependence
RUN pip install --no-cache-dir -r requirements_docker.txt

# Copy the rest of the application
COPY . .

# Environment setup
ENV PYTHONUNBUFFERED=1
ENV PIPELINE_AUTOMATIC=1
ENV MPLBACKEND=Agg
# Xvfb setup envs for SeleniumBase if needed (SB handles some, but good to have)
ENV DISPLAY=:99

# Create the start script directly in /app
RUN echo '#!/bin/bash\nXvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &\npython /app/bootstrapper.py' > /app/start.sh && chmod +x /app/start.sh

# Use the absolute path for the CMD
CMD ["/bin/bash", "/app/start.sh"]
import sys
import multiprocessing

# # Windows RQ Fix: Map 'fork' to 'spawn' so the RQ module can import on Windows
if sys.platform == "win32":
    _orig_get_context = multiprocessing.get_context
    def _patched_get_context(method=None):
        if method == 'fork':
            method = 'spawn'
        return _orig_get_context(method)
    multiprocessing.get_context = _patched_get_context

multiprocessing.set_start_method('spawn', force=True)

import os
import json
import redis
from rq import SimpleWorker, Queue



# ================= GLOBAL CONFIG =================
REDIS_HOST = "127.0.0.1"
QUEUE_NAME = "video_jobs"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_GEN_DIR = os.path.join(BASE_DIR, "video-gen")

def start_worker():
    """
    Sub-process entry point to boot an individual WindowsWorker.
    """
    rq_redis = redis.Redis(host=REDIS_HOST, port=6379)
    queue = Queue(QUEUE_NAME, connection=rq_redis)

    # Pass both the queue list and the connection explicitly
    worker = SimpleWorker([queue], connection=rq_redis)
    worker.work()

if __name__ == "__main__":
    MAX_CONCURRENCY = 1
    config_path = os.path.join(VIDEO_GEN_DIR, "config.json")
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                v_config = json.load(f)
                MAX_CONCURRENCY = v_config.get("no_of_concurrent_generations", 1)
        except Exception as e:
            print("Failed to load config:", e)

    print(f"Starting WindowsWorker processes...")
    
    start_worker()    

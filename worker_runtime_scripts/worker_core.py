import sys
import multiprocessing


from rq import Worker
import os
import json
import redis
from rq import SimpleWorker, Queue

import rq.timeouts

# ================= GLOBAL CONFIG =================
REDIS_HOST = "gjzqxbrmsx.localto.net"
REDIS_PORT = 6245
BURST_WORKER_WHEN_INACTIVE = True
QUEUE_NAME = "video_jobs"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_GEN_DIR = os.path.join(BASE_DIR, "video-gen")
class NoOpDeathPenalty:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
def start_worker():
    """
    Sub-process entry point to boot an individual WindowsWorker.
    """
    rq_redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
    queue = Queue(QUEUE_NAME, connection=rq_redis)
    worker = SimpleWorker(
        [queue],
        connection=rq_redis,
    )
    # For windows, we need to disable the death penalty which relies on signals that don't work well with the spawn method
    worker.death_penalty_class = NoOpDeathPenalty
    
    worker.work(burst=BURST_WORKER_WHEN_INACTIVE)

if __name__ == "__main__":
    if sys.platform == "win32":
        _orig_get_context = multiprocessing.get_context
        def _patched_get_context(method=None):
            if method == 'fork':
                method = 'spawn'
            return _orig_get_context(method)
        multiprocessing.get_context = _patched_get_context

    multiprocessing.set_start_method('spawn', force=True)

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

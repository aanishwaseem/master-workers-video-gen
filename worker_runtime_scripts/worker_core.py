import sys
import multiprocessing
import os
import json
import redis
from rq import SimpleWorker, Queue

import rq.timeouts

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

# ================= GLOBAL CONFIG =================
REDIS_HOST = config.get('redis_host')
REDIS_PORT = config.get('redis_port')
BURST_WORKER_WHEN_INACTIVE = config.get('worker_burst_when_inactive')
QUEUE_NAME = config.get('worker_queue_name')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_GEN_DIR = os.path.join(BASE_DIR, config.get('video_gen_dir_name'))
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
    MAX_CONCURRENCY = config.get("worker_max_concurrency", 1)

    print(f"Starting {MAX_CONCURRENCY} WindowsWorker processes...")
    
    processes = []
    for _ in range(MAX_CONCURRENCY):
        p = multiprocessing.Process(target=start_worker)
        p.start()
        processes.append(p)

    for p in processes:
        p.join()    

import sys
import multiprocessing
import os
import collections
import collections.abc
collections.Callable = collections.abc.Callable
import json
import redis
from rq import Worker, Queue

import rq.timeouts

def get_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

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
    config = get_config()
    
    rq_redis = redis.Redis(host=config.get('redis_host'), port=config.get('redis_port'))
    queue = Queue(config.get('worker_queue_name'), connection=rq_redis)
    worker = Worker(
        [queue],
        connection=rq_redis,
    )
    # For windows, we need to disable the death penalty which relies on signals that don't work well with the spawn method
    # worker.death_penalty_class = NoOpDeathPenalty
    
    worker.work(burst=config.get('worker_burst_when_inactive'))

if __name__ == "__main__":
    if sys.platform == "win32":
        _orig_get_context = multiprocessing.get_context
        def _patched_get_context(method=None):
            if method == 'fork':
                method = 'spawn'
            return _orig_get_context(method)
        multiprocessing.get_context = _patched_get_context
    
    config = get_config()
    MAX_CONCURRENCY = config.get("worker_max_concurrency", 1)

    print(f"Starting {MAX_CONCURRENCY} WindowsWorker processes...")
    
    processes = []
    for _ in range(MAX_CONCURRENCY):
        p = multiprocessing.Process(target=start_worker)
        p.start()
        processes.append(p)

    for p in processes:
        p.join()    

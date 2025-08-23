import os, asyncio

GLOBAL_CONCURRENCY = int(os.getenv("GLOBAL_CONCURRENCY", "3"))
REQUEST_SEMAPHORE = asyncio.Semaphore(GLOBAL_CONCURRENCY)

_user_locks: dict[int, asyncio.Lock] = {}

def user_lock(uid: int) -> asyncio.Lock:
    lock = _user_locks.get(uid)
    if lock is None:
        lock = _user_locks[uid] = asyncio.Lock()
    return lock

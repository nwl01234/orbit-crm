"""Tiny in-memory login throttling.

A single-process demo does not need Redis. The interface is intentionally
small so it can be swapped for a shared store in production.
"""

import threading
import time
from collections import defaultdict, deque

_attempts: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def _prune(key: str, window_seconds: int) -> None:
    cutoff = time.monotonic() - window_seconds
    bucket = _attempts[key]
    while bucket and bucket[0] < cutoff:
        bucket.popleft()


def is_limited(key: str, max_attempts: int, window_seconds: int) -> bool:
    with _lock:
        _prune(key, window_seconds)
        return len(_attempts[key]) >= max_attempts


def record_failure(key: str, window_seconds: int) -> None:
    with _lock:
        _prune(key, window_seconds)
        _attempts[key].append(time.monotonic())


def reset(key: str) -> None:
    with _lock:
        _attempts.pop(key, None)


def retry_after(key: str, window_seconds: int) -> int:
    with _lock:
        bucket = _attempts.get(key)
        if not bucket:
            return 0
        return max(0, int(window_seconds - (time.monotonic() - bucket[0])))

"""
In-process sliding-window rate limiter. Deliberately simple — a dict of
timestamp deques, no external dependency — which is enough for a single
server. If you ever run more than one backend instance, this needs to move
to something shared (Redis INCR + EXPIRE is the usual choice); each
instance would otherwise enforce its own separate limit.
"""
import time
import threading
from collections import defaultdict, deque
from fastapi import HTTPException

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)


def enforce(key: str, max_attempts: int, window_sec: int) -> None:
    """Raises HTTPException(429) if `key` has already hit max_attempts
    within the trailing window_sec seconds; otherwise records this attempt."""
    now = time.time()
    with _lock:
        bucket = _hits[key]
        while bucket and now - bucket[0] > window_sec:
            bucket.popleft()
        if len(bucket) >= max_attempts:
            retry_after = int(window_sec - (now - bucket[0]))
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please wait before trying again.",
                headers={"Retry-After": str(max(retry_after, 1))},
            )
        bucket.append(now)


def client_key(request, *parts: str) -> str:
    """Builds a rate-limit key from the caller's IP plus extra context
    (e.g. the email being attempted) so a single IP can't lock out a
    different account's attempts, and vice versa."""
    ip = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        ip = fwd.split(",")[0].strip()
    return ":".join([ip, *parts])

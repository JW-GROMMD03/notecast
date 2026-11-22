"""
backend/app/cache.py
Thread-safe O(1) LRU + TTL In-Memory Cache with Single-Flight Stampede Protection
and optional Redis L2 write-through synchronization.
"""
from collections import OrderedDict
import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("notecast_cache")


class LRUTTLCache:
    """
    O(1) get/set/delete LRU cache using OrderedDict (Hash Map + Doubly-Linked List)
    paired with monotonic TTL expiration and per-key single-flight locks.
    """

    def __init__(self, max_items: int = 512, default_ttl: int = 3600):
        self.max_items = max_items
        self.default_ttl = default_ttl
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.RLock()
        self._key_locks: dict[str, threading.Lock] = {}
        self._redis = self._init_redis()

    def _init_redis(self):
        redis_url = os.getenv("REDIS_URL", "").strip()
        redis_host = os.getenv("REDIS_HOST", "").strip()
        if not redis_url and not redis_host:
            return None
        try:
            import redis
            if redis_url:
                client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=0.5,
                    socket_timeout=0.5,
                )
            else:
                client = redis.Redis(
                    host=redis_host,
                    port=int(os.getenv("REDIS_PORT", 6379)),
                    db=0,
                    decode_responses=True,
                    socket_connect_timeout=0.5,
                    socket_timeout=0.5,
                )
            client.ping()
            logger.info("L2 Redis cache connected.")
            return client
        except Exception as exc:
            logger.warning("L2 Redis unavailable, running on L1 in-memory LRU cache: %s", exc)
            return None

    def _get_key_lock(self, key: str) -> threading.Lock:
        with self._lock:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[key] = lock
            return lock

    def get(self, key: str) -> Optional[Any]:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is not None:
                expires_at, value = entry
                if expires_at > now:
                    self._store.move_to_end(key)
                    return value
                del self._store[key]

        # Fallback to L2 Redis if configured
        if self._redis is not None:
            try:
                raw = self._redis.get(key)
                if raw is not None:
                    val = json.loads(raw)
                    self._set_l1(key, val, self.default_ttl)
                    return val
            except Exception as exc:
                logger.debug("Redis read miss/error for %s: %s", key, exc)

        return None

    def _set_l1(self, key: str, value: Any, ttl: int) -> None:
        expires_at = time.monotonic() + ttl
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (expires_at, value)
            while len(self._store) > self.max_items:
                self._store.popitem(last=False)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self.default_ttl
        self._set_l1(key, value, effective_ttl)

        if self._redis is not None:
            try:
                self._redis.setex(key, effective_ttl, json.dumps(value))
            except Exception as exc:
                logger.debug("Redis write error for %s: %s", key, exc)

    def get_or_set(self, key: str, loader: Callable[[], Any], ttl: Optional[int] = None) -> Any:
        """
        Single-flight cache-aside lookup: prevents thundering-herd DB queries
        when multiple clients hit a cold cache key simultaneously.
        """
        cached = self.get(key)
        if cached is not None:
            return cached

        key_lock = self._get_key_lock(key)
        with key_lock:
            cached = self.get(key)
            if cached is not None:
                return cached
            value = loader()
            self.set(key, value, ttl=ttl)
            return value

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)
        if self._redis is not None:
            try:
                self._redis.delete(key)
            except Exception:
                pass

    def delete_prefix(self, prefix: str) -> None:
        with self._lock:
            matching = [k for k in self._store.keys() if k.startswith(prefix)]
            for k in matching:
                del self._store[k]

        if self._redis is not None:
            try:
                for k in self._redis.scan_iter(f"{prefix}*"):
                    self._redis.delete(k)
            except Exception:
                pass

    def bump_version(self, namespace: str) -> str:
        """Increments a monotonic namespace version for O(1) ETag invalidation."""
        ver_key = f"ver:{namespace}"
        new_ver = str(int(time.time() * 1000))
        if self._redis is not None:
            try:
                new_ver = str(self._redis.incr(ver_key))
            except Exception:
                pass
        self._set_l1(ver_key, new_ver, ttl=86400 * 30)
        return new_ver

    def get_version(self, namespace: str) -> str:
        ver_key = f"ver:{namespace}"
        val = self.get(ver_key)
        if val is not None:
            return str(val)
        return self.bump_version(namespace)


# Shared application-wide cache instance
app_cache = LRUTTLCache(max_items=1024, default_ttl=21600)


def compute_etag(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts).encode("utf-8")
    return f'W/"{hashlib.sha256(raw).hexdigest()[:24]}"'
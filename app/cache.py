# app/cache.py
import json
import redis
from redis.exceptions import ConnectionError
from .config import settings

_redis_client: redis.Redis | None = None
_redis_usable: bool | None = None


def get_redis_client() -> redis.Redis | None:
    """
    Return a Redis client if Redis is reachable; otherwise return None.
    This prevents the app from crashing if Redis is down or misconfigured.
    """
    global _redis_client, _redis_usable
    if _redis_usable is False:
        return None

    if _redis_client is None:
        try:
            _redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                decode_responses=True,
            )
            # Test connection once
            _redis_client.ping()
            _redis_usable = True
        except Exception:
            _redis_client = None
            _redis_usable = False
            return None

    return _redis_client


def cache_get_json(key: str):
    client = get_redis_client()
    if client is None:
        return None  # No cache if Redis not available
    try:
        raw = client.get(key)
    except ConnectionError:
        return None
    if raw is None:
        return None
    return json.loads(raw)


def cache_set_json(key: str, value, ttl: int | None = None):
    client = get_redis_client()
    if client is None:
        return  # silently skip caching if Redis not available
    try:
        raw = json.dumps(value, default=str)
        client.setex(key, ttl or settings.cache_ttl_seconds, raw)
    except ConnectionError:
        return


def clear_cache():
    client = get_redis_client()
    if client is None:
        return
    try:
        client.flushdb()
    except ConnectionError:
        return

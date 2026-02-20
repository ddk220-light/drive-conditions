# utils.py — shared unit conversion helpers

import asyncio
import time
from functools import wraps


class AsyncCache:
    def __init__(self, ttl_seconds):
        self.ttl = ttl_seconds
        self.cache = {}

    def get(self, key):
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            else:
                del self.cache[key]
        return None

    def set(self, key, value):
        self.cache[key] = (value, time.time())


def cached_weather_fetcher(ttl_seconds=3600, max_concurrent=5, round_digits=2):
    """
    Decorator for async weather fetchers (lat, lon, session=None).
    Rounds lat/lon for caching purposes to group nearby waypoints.
    Limits concurrency using a Semaphore.
    """
    cache = AsyncCache(ttl_seconds)
    semaphore = asyncio.Semaphore(max_concurrent)

    def decorator(func):
        @wraps(func)
        async def wrapper(lat, lon, session=None, **kwargs):
            key = (round(lat, round_digits), round(lon, round_digits))
            cached = cache.get(key)
            if cached is not None:
                return cached

            async with semaphore:
                cached = cache.get(key)
                if cached is not None:
                    return cached
                
                result = await func(lat, lon, session=session, **kwargs)
                cache.set(key, result)
                return result
        return wrapper
    return decorator


def c_to_f(c):
    return round(c * 9 / 5 + 32, 1)


def kmh_to_mph(kmh):
    return round(kmh * 0.621371, 1)


def km_to_miles(km):
    return round(km * 0.621371, 1)


def m_to_miles(m):
    return round(m / 1609.344, 1)


def m_to_ft(m):
    return round(m * 3.28084)

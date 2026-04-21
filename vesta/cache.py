"""Tiny key/value cache used to skip repeated work across cron runs.

Render.com cron jobs run in ephemeral containers with no persistent disk,
so any state that needs to survive between runs must live off-box. This
module exposes a minimal ``Cache`` interface with two backends:

- ``RedisCache`` — the production backend on Render. Set ``REDIS_URL`` to
  a Redis-compatible URL (e.g. the internal URL of a Render Key-Value
  service, or an Upstash Redis URL).
- ``FileCache`` — a JSON file on disk, used as a zero-config fallback for
  local development. Do not rely on this in ephemeral environments.

The factory ``get_cache`` picks Redis when ``REDIS_URL`` is set and
reachable, otherwise it returns a ``FileCache`` writing to the given path.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

REDIS_URL_ENV_VARS = ("REDIS_URL", "CACHE_REDIS_URL")


class Cache(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...


class RedisCache:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.from_url(url, decode_responses=True, socket_timeout=5)
        self._client.ping()
        self._url = url

    def get(self, key: str) -> str | None:
        try:
            return self._client.get(key)
        except Exception as exc:
            log.warning("redis get(%s) failed: %s", key, exc)
            return None

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        try:
            if ttl_seconds and ttl_seconds > 0:
                self._client.set(key, value, ex=ttl_seconds)
            else:
                self._client.set(key, value)
        except Exception as exc:
            log.warning("redis set(%s) failed: %s", key, exc)


class FileCache:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("file cache read failed (%s): %s", self.path, exc)
            return {}

    def _save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data))
        except OSError as exc:
            log.warning("file cache write failed (%s): %s", self.path, exc)

    def get(self, key: str) -> str | None:
        data = self._load()
        entry = data.get(key)
        if not isinstance(entry, dict):
            return None
        expires_at = entry.get("expires_at")
        if isinstance(expires_at, (int, float)) and time.time() > expires_at:
            data.pop(key, None)
            self._save(data)
            return None
        value = entry.get("value")
        return value if isinstance(value, str) else None

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        data = self._load()
        entry: dict = {"value": value}
        if ttl_seconds and ttl_seconds > 0:
            entry["expires_at"] = time.time() + ttl_seconds
        data[key] = entry
        self._save(data)


def get_cache(fallback_path: Path | str) -> Cache:
    """Return the best available cache: Redis if configured, else file-backed."""
    for var in REDIS_URL_ENV_VARS:
        url = os.environ.get(var, "").strip()
        if not url:
            continue
        try:
            cache = RedisCache(url)
            log.info("cache: using redis via %s", var)
            return cache
        except Exception as exc:
            log.warning("cache: %s set but redis unavailable (%s); falling back", var, exc)
            break
    log.info("cache: using file at %s", fallback_path)
    return FileCache(Path(fallback_path))


__all__ = ["Cache", "FileCache", "RedisCache", "get_cache"]

"""Vestaboard Cloud (Read/Write) API client with idempotency cache."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import requests

API_URL = "https://cloud.vestaboard.com/"

log = logging.getLogger(__name__)


def _grid_hash(grid: list[list[int]]) -> str:
    raw = json.dumps(grid, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def send_grid(
    grid: list[list[int]],
    api_key: str,
    cache_path: Path | str = ".last_grid",
    force: bool = False,
) -> bool:
    """Send `grid` to Vestaboard. Returns True if a request was made.

    Skips the POST when the grid is identical to the last successfully
    sent one (tracked in `cache_path`), so cron can run frequently without
    hitting the 1 msg / 15s rate limit.
    """
    cache_path = Path(cache_path)
    new_hash = _grid_hash(grid)

    if not force and cache_path.exists():
        if cache_path.read_text().strip() == new_hash:
            log.info("grid unchanged, skipping send")
            return False

    resp = requests.post(
        API_URL,
        headers={
            "X-Vestaboard-Token": api_key,
            "Content-Type": "application/json",
        },
        json={"characters": grid},
        timeout=15,
    )

    if resp.status_code >= 400:
        log.error("vestaboard send failed: %s %s", resp.status_code, resp.text)
        resp.raise_for_status()

    try:
        body = resp.json()
    except ValueError:
        body = {}
    log.info("vestaboard send ok: %s", body)

    cache_path.write_text(new_hash)
    return True

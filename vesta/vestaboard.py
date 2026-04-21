"""Vestaboard Cloud (Read/Write) API client with idempotency cache."""

from __future__ import annotations

import hashlib
import json
import logging

import requests

from .cache import Cache

LAST_GRID_CACHE_KEY = "vesta:last_grid_hash"

API_URL = "https://cloud.vestaboard.com/"
TRANSITION_URL = "https://cloud.vestaboard.com/transition"

VALID_TRANSITIONS = ("classic", "wave", "drift", "curtain")
VALID_TRANSITION_SPEEDS = ("gentle", "fast")

log = logging.getLogger(__name__)


def _grid_hash(grid: list[list[int]]) -> str:
    raw = json.dumps(grid, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def send_grid(
    grid: list[list[int]],
    api_key: str,
    cache: Cache,
    force: bool = False,
) -> bool:
    """Send ``grid`` to Vestaboard. Returns True if a request was made.

    Skips the POST when the grid is identical to the last successfully
    sent one (tracked in ``cache`` under ``LAST_GRID_CACHE_KEY``), so cron
    can run frequently without hitting the 1 msg / 15s rate limit.
    """
    new_hash = _grid_hash(grid)

    if not force:
        prev = cache.get(LAST_GRID_CACHE_KEY)
        if prev and prev.strip() == new_hash:
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

    cache.set(LAST_GRID_CACHE_KEY, new_hash)
    return True


def set_transition(transition: str, transition_speed: str, api_key: str) -> dict:
    """PUT the device transition settings. Returns the API response body."""
    if transition not in VALID_TRANSITIONS:
        raise ValueError(
            f"transition must be one of {VALID_TRANSITIONS}, got {transition!r}"
        )
    if transition_speed not in VALID_TRANSITION_SPEEDS:
        raise ValueError(
            f"transition_speed must be one of {VALID_TRANSITION_SPEEDS}, "
            f"got {transition_speed!r}"
        )

    resp = requests.put(
        TRANSITION_URL,
        headers={
            "X-Vestaboard-Token": api_key,
            "Content-Type": "application/json",
        },
        json={"transition": transition, "transitionSpeed": transition_speed},
        timeout=15,
    )
    if resp.status_code >= 400:
        log.error("set-transition failed: %s %s", resp.status_code, resp.text)
        resp.raise_for_status()

    try:
        body = resp.json()
    except ValueError:
        body = {}
    log.info("transition set: %s", body)
    return body


def get_transition(api_key: str) -> dict:
    """GET the current device transition settings."""
    resp = requests.get(
        TRANSITION_URL,
        headers={
            "X-Vestaboard-Token": api_key,
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    if resp.status_code >= 400:
        log.error("get-transition failed: %s %s", resp.status_code, resp.text)
        resp.raise_for_status()
    return resp.json()

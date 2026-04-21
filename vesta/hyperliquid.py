"""Hyperliquid BTC price fetch.

Uses the public info endpoint to read the BTC perp mid price (USDC-quoted).
"""

from __future__ import annotations

import logging

import requests

HL_INFO_URL = "https://api.hyperliquid.xyz/info"

log = logging.getLogger(__name__)


def fetch_btc_price() -> float | None:
    try:
        resp = requests.post(
            HL_INFO_URL,
            json={"type": "allMids"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("hyperliquid fetch failed: %s", exc)
        return None

    raw = data.get("BTC") if isinstance(data, dict) else None
    if raw is None:
        log.warning("hyperliquid response missing BTC key: %r", data)
        return None

    try:
        return float(raw)
    except (TypeError, ValueError):
        log.warning("hyperliquid BTC value not numeric: %r", raw)
        return None


def format_btc_k(price: float | None) -> str:
    """Round to the nearest thousand and render as '<N>K'.

    Returns '---K' when the price is unavailable.
    """
    if price is None:
        return "---K"
    thousands = int(round(price / 1000.0))
    return f"{thousands}K"

"""Compose the 15x3 Vestaboard Note grid.

Layout:
    row 0: <DAY> <HHMM>  <BTC>     e.g. ``TDY 0915 104321`` / ``WED 1035 104321``
    row 1: <summary of the next meeting, up to 15 chars>
    row 2: +N TO GO  (next is today) / +N MORE (next is another day) / blank

Day label is ``TDY`` when the next meeting is today, otherwise the weekday
abbreviation (``MON``..``SUN``). All-day events drop the time (e.g.
``TDY 104321`` / ``WED 104321``). BTC is the full rounded dollar price
(no ``K`` suffix), right-aligned; the left-side prefix is truncated to
whatever horizontal room remains.

Row 2's count is how many additional events fall on the same calendar date
as the next meeting. When no upcoming meetings are known, row 0 shows
``NO MTGS`` + BTC and rows 1-2 are blank.
"""

from __future__ import annotations

import datetime as dt
from typing import Sequence

from tzlocal import get_localzone

from .chars import BLANK, sanitize, text_to_codes
from .gcal import Event

COLS = 15
ROWS = 3

_WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _row_codes(text: str) -> list[int]:
    codes = text_to_codes(text)
    if len(codes) < COLS:
        codes = codes + [BLANK] * (COLS - len(codes))
    return codes[:COLS]


def _next_label(event: Event, now_local: dt.datetime) -> str:
    local = event.start.astimezone(now_local.tzinfo)
    if local.date() == now_local.date():
        day = "TDY"
    else:
        day = _WEEKDAYS[local.weekday()]
    if event.all_day:
        return day
    return f"{day} {local.strftime('%H%M')}"


def _compose_row0(prefix: str, btc_label: str) -> str:
    btc = (btc_label or "")[:COLS]
    left_width = max(0, COLS - len(btc))
    left = sanitize(prefix)[:left_width].ljust(left_width)
    return (left + btc)[:COLS]


def _compose_row1(event: Event | None, claude_summary: str | None) -> str:
    if event is None:
        return " " * COLS
    if claude_summary:
        cleaned = sanitize(claude_summary).strip()[:COLS]
    else:
        cleaned = sanitize(event.title).strip()
        cleaned = " ".join(cleaned.split())
        cleaned = cleaned[:COLS]
    return cleaned.ljust(COLS)[:COLS]


def _count_same_day(
    events: Sequence[Event], now_local: dt.datetime
) -> tuple[int, bool]:
    """Count additional events that fall on the same calendar date as the
    next meeting. Returns (count, is_today)."""
    if len(events) <= 1:
        return 0, True
    tz = now_local.tzinfo
    pivot_date = events[0].start.astimezone(tz).date()
    count = sum(
        1 for ev in events[1:] if ev.start.astimezone(tz).date() == pivot_date
    )
    return count, pivot_date == now_local.date()


def _compose_row2(count: int, is_today: bool) -> str:
    if count <= 0:
        return " " * COLS
    word = "TO GO" if is_today else "MORE"
    return f"+{count} {word}".ljust(COLS)[:COLS]


def compose_grid(
    events: Sequence[Event],
    btc_label: str,
    claude_summary: str | None = None,
) -> list[list[int]]:
    now_local = dt.datetime.now(get_localzone())

    if events:
        prefix = f"{_next_label(events[0], now_local)} "
    else:
        prefix = "NO MTGS "

    row0 = _compose_row0(prefix, btc_label)
    row1 = _compose_row1(events[0] if events else None, claude_summary)
    count, is_today = _count_same_day(events, now_local)
    row2 = _compose_row2(count, is_today)

    return [_row_codes(row0), _row_codes(row1), _row_codes(row2)]

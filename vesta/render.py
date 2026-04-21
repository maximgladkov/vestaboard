"""Compose the 15x3 Vestaboard Note grid.

Layout:
    row 0: <meeting 1 title>            NNNK    (BTC right-aligned)
    row 1: HHMM <meeting 2 title>
    row 2: HHMM <meeting 3 title>

Meetings beyond what fits, or a missing BTC value, degrade gracefully
(blank rows / "---K").
"""

from __future__ import annotations

import datetime as dt
from typing import Sequence

from tzlocal import get_localzone

from .chars import BLANK, text_to_codes, sanitize
from .gcal import Event

COLS = 15
ROWS = 3


_WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _time_label(event: Event, now_local: dt.datetime) -> str:
    local = event.start.astimezone(now_local.tzinfo)
    if local.date() == now_local.date():
        if event.all_day:
            return "TDY"
        return local.strftime("%H%M")
    return _WEEKDAYS[local.weekday()]


def _fit(text: str, width: int) -> str:
    clean = sanitize(text).strip()
    clean = " ".join(clean.split())
    if len(clean) <= width:
        return clean.ljust(width)
    return clean[:width]


def _row_codes(text: str) -> list[int]:
    codes = text_to_codes(text)
    if len(codes) < COLS:
        codes = codes + [BLANK] * (COLS - len(codes))
    return codes[:COLS]


def compose_grid(events: Sequence[Event], btc_label: str) -> list[list[int]]:
    now_local = dt.datetime.now(get_localzone())

    btc_label = btc_label.strip()
    if len(btc_label) > COLS:
        btc_label = btc_label[-COLS:]

    rows: list[list[int]] = []

    title_width_row0 = max(0, COLS - len(btc_label) - 1)
    if events:
        meeting1_title = _fit(events[0].title, title_width_row0) if title_width_row0 > 0 else ""
    else:
        meeting1_title = " " * title_width_row0
    row0_text = meeting1_title
    row0_text = row0_text.ljust(COLS - len(btc_label)) + btc_label
    rows.append(_row_codes(row0_text))

    for i in (1, 2):
        if i < len(events):
            ev = events[i]
            label = _time_label(ev, now_local)
            remaining = COLS - len(label) - 1
            title = _fit(ev.title, remaining) if remaining > 0 else ""
            row_text = f"{label} {title}" if remaining > 0 else label
        else:
            row_text = ""
        rows.append(_row_codes(row_text.ljust(COLS)))

    return rows

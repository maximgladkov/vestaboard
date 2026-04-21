#!/usr/bin/env python3
"""Entry point for the Vestaboard Note cron job.

Fetches upcoming Google Calendar events (across every authorized account
in ``tokens/``) and the current Hyperliquid BTC price, composes a 15x3
grid, and POSTs it to the Vestaboard Cloud API.

Layout:
    row 0: NEXT <label>  <BTC>    label is HHMM for today, weekday for other days
    row 1: <summary of the next meeting (Claude, or title truncation)>
    row 2: +N TO GO               (blank when N == 0)

Usage:
    python vestaboard_cron.py                  # normal cron run
    python vestaboard_cron.py --add-account N  # authorize a new Google account
    python vestaboard_cron.py --list-accounts  # show configured accounts
    python vestaboard_cron.py --dry-run        # render but don't send
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from vesta.claude import summarize_title
from vesta.gcal import add_account, fetch_next_events, list_configured_accounts
from vesta.hyperliquid import fetch_btc_price, format_btc_k
from vesta.render import COLS, compose_grid
from vesta.vestaboard import (
    VALID_TRANSITIONS,
    VALID_TRANSITION_SPEEDS,
    get_transition,
    send_grid,
    set_transition,
)


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Vestaboard Note: meetings + BTC")
    p.add_argument(
        "--add-account",
        metavar="NAME",
        help="Interactively authorize a new Google account and save its token.",
    )
    p.add_argument(
        "--list-accounts",
        action="store_true",
        help="List authorized Google accounts (token files) and exit.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compose and log the grid but do not send to Vestaboard.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Send even if the rendered grid matches the cached last send.",
    )
    p.add_argument(
        "--no-ai",
        action="store_true",
        help="Skip Claude summarization and use the raw (truncated) meeting title.",
    )
    p.add_argument(
        "--set-transition",
        nargs=2,
        metavar=("TRANSITION", "SPEED"),
        help=(
            "Set the device transition and exit. "
            f"TRANSITION in {list(VALID_TRANSITIONS)}, "
            f"SPEED in {list(VALID_TRANSITION_SPEEDS)}. "
            "Example: --set-transition wave fast"
        ),
    )
    p.add_argument(
        "--get-transition",
        action="store_true",
        help="Print the device's current transition settings and exit.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("vestaboard_cron")

    root = Path(__file__).resolve().parent
    _load_dotenv(root / ".env")

    tokens_dir = root / "tokens"

    if args.list_accounts:
        names = list_configured_accounts(tokens_dir)
        if not names:
            print(
                "No accounts configured yet. Run with --add-account <name>, "
                "or set GOOGLE_TOKEN_<NAME> env vars."
            )
            return 0
        for name in names:
            print(name)
        return 0

    if args.add_account:
        try:
            add_account(
                args.add_account,
                credentials_path=root / "credentials.json",
                tokens_dir=tokens_dir,
            )
        except Exception:
            log.exception("add-account failed")
            return 1
        print(f"Authorized account: {args.add_account}")
        return 0

    api_key = os.environ.get("VESTABOARD_API_KEY")

    if args.get_transition or args.set_transition:
        if not api_key:
            log.error("VESTABOARD_API_KEY is not set (check .env)")
            return 2
        try:
            if args.set_transition:
                transition, speed = args.set_transition
                body = set_transition(transition, speed, api_key)
            else:
                body = get_transition(api_key)
        except Exception:
            log.exception("transition command failed")
            return 1
        print(body)
        return 0

    if not api_key and not args.dry_run:
        log.error("VESTABOARD_API_KEY is not set (check .env)")
        return 2

    try:
        events = fetch_next_events(count=25, tokens_dir=tokens_dir)
    except Exception:
        log.exception("failed to fetch calendar events")
        events = []

    btc_price = fetch_btc_price()
    btc_label = format_btc_k(btc_price)
    log.info("btc=%s events=%d", btc_label, len(events))
    for ev in events:
        log.info(
            "  [%s] %s @ %s",
            ev.account,
            ev.title,
            ev.start.isoformat(),
        )

    claude_summary: str | None = None
    if events and not args.no_ai:
        claude_summary = summarize_title(events[0], max_chars=COLS)
        if claude_summary:
            log.info("claude summary: %r", claude_summary)
        else:
            log.info("no claude summary; falling back to raw title")

    grid = compose_grid(events, btc_label, claude_summary=claude_summary)

    for row in grid:
        log.info("row: %s", row)

    if args.dry_run:
        log.info("dry-run: not sending")
        return 0

    try:
        send_grid(
            grid,
            api_key=api_key,
            cache_path=root / ".last_grid",
            force=args.force,
        )
    except Exception:
        log.exception("failed to send to vestaboard")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Entry point for the Vestaboard Note cron job.

Fetches the next 3 Google Calendar events (across every authorized account
in ``tokens/``) and the current Hyperliquid BTC price, composes a 15x3
grid, and POSTs it to the Vestaboard Cloud API.

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

from vesta.gcal import add_account, fetch_next_events
from vesta.hyperliquid import fetch_btc_price, format_btc_k
from vesta.render import compose_grid
from vesta.vestaboard import send_grid


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
        if not tokens_dir.exists():
            print("No accounts configured yet. Run with --add-account <name>.")
            return 0
        files = sorted(tokens_dir.glob("*.json"))
        if not files:
            print("No accounts configured yet. Run with --add-account <name>.")
            return 0
        for f in files:
            print(f.stem)
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
    if not api_key and not args.dry_run:
        log.error("VESTABOARD_API_KEY is not set (check .env)")
        return 2

    try:
        events = fetch_next_events(count=3, tokens_dir=tokens_dir)
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

    grid = compose_grid(events, btc_label)
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

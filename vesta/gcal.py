"""Google Calendar: fetch the next N upcoming events across multiple accounts.

Each Google account has its own token file under ``tokens/<name>.json``. A
shared OAuth client (``credentials.json``) is reused across accounts. Use
``add_account`` to interactively authorize a new account; cron runs load
every token in the directory and merge events.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

from dateutil import parser as dtparser
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

log = logging.getLogger(__name__)


@dataclass
class Event:
    title: str
    start: dt.datetime
    all_day: bool
    account: str = ""


def _load_creds_headless(token_path: Path) -> Credentials | None:
    """Load + refresh credentials without any browser interaction.

    Returns None when the token is missing, invalid, or can't be refreshed
    silently. The caller should log and continue with other accounts.
    """
    if not token_path.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except ValueError as exc:
        log.warning("invalid token file %s: %s", token_path, exc)
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            log.warning("token refresh failed for %s: %s", token_path.name, exc)
            return None
        token_path.write_text(creds.to_json())
        return creds

    return None


def add_account(
    name: str,
    credentials_path: Path | str = "credentials.json",
    tokens_dir: Path | str = "tokens",
) -> Path:
    """Run the OAuth browser flow and save a token at ``tokens/<name>.json``.

    Must be run interactively (not from cron) the first time each account
    is added.
    """
    credentials_path = Path(credentials_path)
    tokens_dir = Path(tokens_dir)
    tokens_dir.mkdir(parents=True, exist_ok=True)

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Missing Google OAuth client secret at {credentials_path}. "
            "Create a Desktop OAuth client in Google Cloud Console and save it there."
        )

    token_path = tokens_dir / f"{name}.json"
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    log.info("saved token for account %r to %s", name, token_path)
    return token_path


def _parse_start(ev: dict) -> tuple[dt.datetime | None, bool]:
    start = ev.get("start", {}) or {}
    if "dateTime" in start:
        return dtparser.isoparse(start["dateTime"]), False
    if "date" in start:
        d = dtparser.isoparse(start["date"]).date()
        return dt.datetime.combine(d, dt.time.min, tzinfo=dt.timezone.utc), True
    return None, False


def _self_declined(ev: dict) -> bool:
    for attendee in ev.get("attendees", []) or []:
        if attendee.get("self") and attendee.get("responseStatus") == "declined":
            return True
    return False


def _fetch_for_account(
    service, account_name: str, time_min_iso: str, per_cal_limit: int
) -> list[Event]:
    out: list[Event] = []
    try:
        cal_list = service.calendarList().list().execute()
    except HttpError as exc:
        log.warning("[%s] calendarList.list failed: %s", account_name, exc)
        return out

    for cal in cal_list.get("items", []):
        cal_id = cal.get("id")
        if not cal_id:
            continue
        if cal.get("selected") is False:
            continue
        try:
            resp = (
                service.events()
                .list(
                    calendarId=cal_id,
                    timeMin=time_min_iso,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=per_cal_limit,
                )
                .execute()
            )
        except HttpError as exc:
            log.warning("[%s] events.list failed for %s: %s", account_name, cal_id, exc)
            continue
        for ev in resp.get("items", []):
            if ev.get("status") == "cancelled":
                continue
            if _self_declined(ev):
                continue
            start, all_day = _parse_start(ev)
            if start is None:
                continue
            title = ev.get("summary") or "(NO TITLE)"
            out.append(Event(title=title, start=start, all_day=all_day, account=account_name))
    return out


def fetch_next_events(
    count: int = 3,
    tokens_dir: Path | str = "tokens",
) -> list[Event]:
    tokens_dir = Path(tokens_dir)
    if not tokens_dir.exists():
        log.warning("tokens directory %s does not exist; no accounts configured", tokens_dir)
        return []

    token_files = sorted(tokens_dir.glob("*.json"))
    if not token_files:
        log.warning("no token files in %s; add an account with --add-account", tokens_dir)
        return []

    now = dt.datetime.now(dt.timezone.utc)
    time_min = now.isoformat().replace("+00:00", "Z")

    collected: list[Event] = []
    for token_path in token_files:
        account_name = token_path.stem
        creds = _load_creds_headless(token_path)
        if creds is None:
            log.warning(
                "[%s] no usable credentials; re-run with --add-account %s",
                account_name,
                account_name,
            )
            continue
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        collected.extend(
            _fetch_for_account(service, account_name, time_min, per_cal_limit=count + 5)
        )

    upcoming = [e for e in collected if e.start >= now - dt.timedelta(minutes=1)]
    upcoming.sort(key=lambda e: e.start)
    return upcoming[:count]


__all__ = ["Event", "add_account", "fetch_next_events"]

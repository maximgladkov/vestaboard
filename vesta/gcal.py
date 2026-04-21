"""Google Calendar: fetch the next N upcoming events across multiple accounts.

Sources of credentials, in order of precedence:

1. Environment variables (useful for containers / servers):
   - ``GOOGLE_CREDENTIALS_JSON``  -> raw JSON for the OAuth client
     (equivalent to the contents of ``credentials.json``).
   - ``GOOGLE_TOKEN_<NAME>``      -> raw JSON for a specific authorized
     account's token (equivalent to ``tokens/<name>.json``). The ``<NAME>``
     is upper-cased; e.g. ``GOOGLE_TOKEN_PERSONAL`` loads an account named
     ``personal``.
2. On-disk files:
   - ``credentials.json`` at the project root.
   - ``tokens/<name>.json`` per authorized account.

For tokens, env vars add to the file-based set; if an account is defined in
both places the env var wins (and the refreshed copy is still cached to
``tokens/<name>.json`` when that directory is writable, so subsequent
disk-only runs keep working).

Use ``add_account`` to interactively authorize a new account; cron runs
load every configured account and merge events.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
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

CREDENTIALS_ENV_VAR = "GOOGLE_CREDENTIALS_JSON"
TOKEN_ENV_PREFIX = "GOOGLE_TOKEN_"

log = logging.getLogger(__name__)


@dataclass
class Event:
    title: str
    start: dt.datetime
    all_day: bool
    account: str = ""


def _load_client_config(credentials_path: Path) -> dict | None:
    """Return the OAuth client config dict from env or file, or None."""
    env = os.environ.get(CREDENTIALS_ENV_VAR, "").strip()
    if env:
        try:
            return json.loads(env)
        except json.JSONDecodeError as exc:
            log.warning("%s is not valid JSON: %s", CREDENTIALS_ENV_VAR, exc)
    if credentials_path.exists():
        try:
            return json.loads(credentials_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("could not read %s: %s", credentials_path, exc)
    return None


def _creds_from_info(info: dict, writeback: Path | None) -> Credentials | None:
    """Build Credentials from an authorized-user info dict and refresh as needed."""
    try:
        creds = Credentials.from_authorized_user_info(info, SCOPES)
    except (ValueError, KeyError) as exc:
        log.warning("invalid authorized-user data: %s", exc)
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            log.warning("token refresh failed: %s", exc)
            return None
        if writeback is not None:
            try:
                writeback.parent.mkdir(parents=True, exist_ok=True)
                writeback.write_text(creds.to_json())
            except OSError as exc:
                log.warning("couldn't cache refreshed token to %s: %s", writeback, exc)
        return creds

    return None


def _discover_token_sources(tokens_dir: Path) -> dict[str, tuple[str, object]]:
    """Return a mapping of ``account_name -> (kind, payload)``.

    ``kind`` is ``"env"`` (payload is the raw JSON string) or ``"file"``
    (payload is the Path to the token file). Env vars take precedence over
    files when the same account is defined in both places.
    """
    sources: dict[str, tuple[str, object]] = {}

    if tokens_dir.exists():
        for p in sorted(tokens_dir.glob("*.json")):
            sources[p.stem] = ("file", p)

    for key, value in os.environ.items():
        if not key.startswith(TOKEN_ENV_PREFIX):
            continue
        if not value:
            continue
        account = key[len(TOKEN_ENV_PREFIX) :].lower()
        if not account:
            continue
        sources[account] = ("env", value)

    return sources


def _load_creds_headless(
    account_name: str,
    kind: str,
    payload: object,
    tokens_dir: Path,
) -> Credentials | None:
    """Load + refresh credentials without any browser interaction."""
    if kind == "file":
        assert isinstance(payload, Path)
        if not payload.exists():
            return None
        try:
            info = json.loads(payload.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("invalid token file %s: %s", payload, exc)
            return None
        return _creds_from_info(info, writeback=payload)

    if kind == "env":
        assert isinstance(payload, str)
        try:
            info = json.loads(payload)
        except json.JSONDecodeError as exc:
            log.warning(
                "%s%s is not valid JSON: %s",
                TOKEN_ENV_PREFIX,
                account_name.upper(),
                exc,
            )
            return None
        writeback = tokens_dir / f"{account_name}.json"
        if not tokens_dir.exists():
            writeback = None
        return _creds_from_info(info, writeback=writeback)

    log.warning("unknown token source kind: %s", kind)
    return None


def add_account(
    name: str,
    credentials_path: Path | str = "credentials.json",
    tokens_dir: Path | str = "tokens",
) -> Path:
    """Run the OAuth browser flow and save a token at ``tokens/<name>.json``.

    Must be run interactively (not from cron) the first time each account
    is added. Reads the OAuth client config from the
    ``GOOGLE_CREDENTIALS_JSON`` env var first, then falls back to
    ``credentials.json``.
    """
    credentials_path = Path(credentials_path)
    tokens_dir = Path(tokens_dir)
    tokens_dir.mkdir(parents=True, exist_ok=True)

    client_config = _load_client_config(credentials_path)
    if client_config is None:
        raise FileNotFoundError(
            f"No OAuth client found. Set {CREDENTIALS_ENV_VAR} or create "
            f"{credentials_path}. Use a Desktop OAuth client from Google "
            "Cloud Console."
        )

    token_path = tokens_dir / f"{name}.json"
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
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


def list_configured_accounts(tokens_dir: Path | str = "tokens") -> list[str]:
    """Return the names of all accounts configured via files or env vars."""
    return sorted(_discover_token_sources(Path(tokens_dir)).keys())


def fetch_next_events(
    count: int = 3,
    tokens_dir: Path | str = "tokens",
) -> list[Event]:
    tokens_dir = Path(tokens_dir)

    sources = _discover_token_sources(tokens_dir)
    if not sources:
        log.warning(
            "no token sources found (checked %s and %s* env vars)",
            tokens_dir,
            TOKEN_ENV_PREFIX,
        )
        return []

    now = dt.datetime.now(dt.timezone.utc)
    time_min = now.isoformat().replace("+00:00", "Z")

    collected: list[Event] = []
    for account_name, (kind, payload) in sorted(sources.items()):
        creds = _load_creds_headless(account_name, kind, payload, tokens_dir)
        if creds is None:
            log.warning(
                "[%s] no usable credentials (source=%s); re-run with "
                "--add-account %s",
                account_name,
                kind,
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


__all__ = [
    "Event",
    "add_account",
    "fetch_next_events",
    "list_configured_accounts",
]

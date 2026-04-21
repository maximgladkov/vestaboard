# Vestaboard Note: Next Meetings + BTC

Python cron script that renders a 15x3 Vestaboard Note with:

- Next 3 upcoming Google Calendar events (across all calendars on your account) on the left
- Current BTC price (Hyperliquid perp mid, USDC-quoted) rounded to the nearest thousand with a `K` suffix in the top-right

## Layout (15 cols x 3 rows)

```
row 0: <meeting 1 title>            NNNK
row 1: HHMM <meeting 2 title>
row 2: HHMM <meeting 3 title>
```

The BTC value is right-aligned on row 0; meeting 1's title is truncated to fit the remaining space. Meeting time labels:

- `HHMM` if the event is today (local time)
- `TDY` if it's an all-day event today
- `MON` / `TUE` / ... / `SUN` if it's on a different day

## Setup

1. Create and activate a virtualenv, then install dependencies:

   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Get a Vestaboard Read/Write API key from the Vestaboard web app and put it in `.env`:

   ```
   cp .env.example .env
   # edit .env and set VESTABOARD_API_KEY
   ```

3. Create Google OAuth credentials (Desktop app) at
   <https://console.cloud.google.com/apis/credentials>, enable the Google Calendar
   API, download the JSON as `credentials.json` in this directory. The same
   OAuth client is reused for every Google account you connect.

   If the client is in "Testing" mode, add each Google account you plan to
   connect as a Test User under the OAuth consent screen.

4. Authorize each Google account you want to pull events from. Pick any label
   per account (used only as the token filename):

   ```
   python vestaboard_cron.py --add-account personal
   python vestaboard_cron.py --add-account work
   ```

   A browser window opens for each; sign in with the corresponding Google
   account. Tokens are saved to `tokens/<name>.json` and used headlessly
   from cron afterwards.

   List authorized accounts:

   ```
   python vestaboard_cron.py --list-accounts
   ```

   Revoking is as simple as deleting the file in `tokens/` (and revoking the
   app from the Google account's security page).

5. Test a dry run (composes the grid and logs it without sending):

   ```
   python vestaboard_cron.py --dry-run
   ```

## Cron

Every 5 minutes (Vestaboard rate-limits to 1 msg / 15s; the script also
skips sending if the rendered grid is unchanged):

```
*/5 * * * * cd /Users/mgladkov/Projects/personal/vestaboard && /Users/mgladkov/Projects/personal/vestaboard/.venv/bin/python vestaboard_cron.py >> cron.log 2>&1
```

## Files

- `vestaboard_cron.py` — entry point
- `vesta/chars.py` — Vestaboard character map
- `vesta/hyperliquid.py` — BTC price fetch
- `vesta/gcal.py` — Google Calendar fetch
- `vesta/render.py` — 15x3 grid composition
- `vesta/vestaboard.py` — Vestaboard API client with idempotency cache

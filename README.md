# Vestaboard Note: Next Meetings + BTC

Python cron script that renders a 15x3 Vestaboard Note with the next meeting
and the current BTC price from Hyperliquid.

## Layout (15 cols x 3 rows)

```
row 0: NEXT <label>  <BTC>
row 1: <summary of the next meeting>
row 2: +N TO GO
```

- Row 0 always starts with `NEXT` followed by a label and the BTC value
  right-aligned. Label rules:
  - `HHMM` if the next event is today (local time), e.g. `NEXT 1230  104K`
  - `TDY` if it's an all-day event today
  - `MON` / `TUE` / ... / `SUN` if it's on a different day, e.g. `NEXT WED   104K`
- Row 1 is a summary of the next meeting's title, at most 15 characters.
- Row 2 shows how many additional meetings fall on the same calendar date
  as the next meeting:
  - `+N TO GO` when the next meeting is today
  - `+N MORE` when the next meeting is on another day
  - blank when there are no additional same-day events
- If there are no upcoming meetings at all, row 0 becomes `NO MTGS` with the
  BTC value and rows 1-2 are blank.

## AI mode (Claude)

If `ANTHROPIC_API_KEY` is set in `.env`, the script asks Anthropic Claude to
write the row-1 summary for you — a telegraphic, Vestaboard-safe rewrite of
the next meeting's title, at most 15 characters. If Claude's output fails
validation, it is sent back with the specific error and asked to correct
itself, up to 3 rounds. On final failure the script falls back to the
truncated raw title.

Override the model with `ANTHROPIC_MODEL=...` in `.env` (defaults to
`claude-haiku-4-5`). Disable AI entirely with `--no-ai`.

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

## Credentials from environment variables

Both the OAuth client and per-account tokens can be injected via environment
variables instead of files, which is handy on servers / containers / CI:

- `GOOGLE_CREDENTIALS_JSON` — raw JSON contents of `credentials.json` (the
  Desktop OAuth client). Used by `--add-account` when present.
- `GOOGLE_TOKEN_<NAME>` — raw JSON contents for a single authorized
  account's token, equivalent to `tokens/<name>.json`. `<NAME>` is the
  upper-cased account label, e.g. `GOOGLE_TOKEN_PERSONAL`,
  `GOOGLE_TOKEN_WORK`.

Precedence when both a file and an env var are defined for the same account:
the env var wins. When the `tokens/` directory is writable, the refreshed
token is also cached to disk for faster subsequent runs.

Tokens from env vars also appear under `--list-accounts`.

## Device transitions

The Vestaboard Cloud API exposes transition settings per device. Read and
write them via the CLI:

```
python vestaboard_cron.py --get-transition
python vestaboard_cron.py --set-transition wave fast
```

Valid transitions: `classic`, `wave`, `drift`, `curtain`.
Valid speeds: `gentle`, `fast`.

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
- `vesta/render.py` — 15x3 grid composition (NEXT / summary / +N TO GO)
- `vesta/claude.py` — Claude-powered title summarization for row 1
- `vesta/vestaboard.py` — Vestaboard API client with idempotency cache

# Vestaboard Note: Next Meetings + BTC

Python cron script that renders a 15x3 Vestaboard Note with the next meeting
and the current BTC price from Hyperliquid.

## Layout (15 cols x 3 rows)

```
row 0: <DAY> <HHMM>  <BTC>
row 1: <summary of the next meeting>
row 2: +N TO GO
```

- Row 0 is the next meeting's day + start time on the left, and the BTC
  value (full rounded dollar price, no `K` suffix) right-aligned. Label
  rules:
  - `TDY <HHMM>` if the next event is today (local time), e.g. `TDY 0915 104321`
  - `<DAY> <HHMM>` on another day, e.g. `WED 1035 104321`
  - `TDY` or `<DAY>` alone for all-day events (no time component)
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

Summaries are cached keyed by the event's (account, title, start, budget,
model) so the next cron run reuses the previous Claude response as long
as the "next" meeting is still the same one. The cache also stores the
hash of the last sent grid, so the Vestaboard send is skipped when
nothing changed. See [Caching](#caching) below.

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

## Caching

To avoid unnecessary Claude calls and unnecessary Vestaboard sends, the
script persists two things between runs:

- the Claude summary for the current "next" meeting
  (key: `vesta:claude:<hash(account|title|start|budget|model)>`, 30-day TTL)
- the SHA-256 of the last grid actually POSTed to Vestaboard
  (key: `vesta:last_grid_hash`)

Backends, in order of preference:

1. Redis, when `REDIS_URL` (or `CACHE_REDIS_URL`) is set. Required on
   render.com cron jobs, which run in ephemeral containers with no
   persistent disk.
2. A local `.cache.json` file, as a zero-config fallback for development.

Any Redis-compatible URL works, e.g. a Render Key-Value service
(`redis://...` internal URL) or Upstash Redis (`rediss://...`). Failures
to reach Redis fall back to the file cache automatically.

## Cron

Every 5 minutes (Vestaboard rate-limits to 1 msg / 15s; the script also
skips sending if the rendered grid is unchanged):

```
*/5 * * * * cd /Users/mgladkov/Projects/personal/vestaboard && /Users/mgladkov/Projects/personal/vestaboard/.venv/bin/python vestaboard_cron.py >> cron.log 2>&1
```

### Render.com

Deploy as a Render Cron Job:

1. Create a Render **Key-Value** (Redis) service in the same region.
2. Create a **Cron Job** pointing at this repo.
   - Build command: `pip install -r requirements.txt`
   - Command: `python vestaboard_cron.py`
   - Schedule: e.g. `*/5 * * * *`
3. Set environment variables on the cron job:
   - `VESTABOARD_API_KEY`, `ANTHROPIC_API_KEY`, `TZ`
   - `GOOGLE_CREDENTIALS_JSON` and one `GOOGLE_TOKEN_<NAME>` per account
     (see above — authorize locally first, then copy the JSON into env vars)
   - `REDIS_URL` = the Key-Value service's **Internal** Redis URL

Render cron jobs have no persistent disk, so `REDIS_URL` is how the
Claude summary and last-grid hash survive between runs. Without it the
script still works but will call Claude and POST to Vestaboard on every
run.

## Files

- `vestaboard_cron.py` — entry point
- `vesta/chars.py` — Vestaboard character map
- `vesta/hyperliquid.py` — BTC price fetch
- `vesta/gcal.py` — Google Calendar fetch
- `vesta/render.py` — 15x3 grid composition (NEXT / summary / +N TO GO)
- `vesta/claude.py` — Claude-powered title summarization for row 1
- `vesta/cache.py` — Redis/file KV used to cache summaries + grid hash
- `vesta/vestaboard.py` — Vestaboard API client with idempotency cache

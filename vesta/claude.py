"""Ask Claude for a short, Vestaboard-safe summary of a meeting title.

The caller gives Claude one meeting (title + account + when) and asks for
a telegraphic summary that fits in ``max_chars`` characters. The result is
validated against Vestaboard's character set; on failure, the specific
error is sent back and Claude is asked to self-correct, up to
``MAX_AUTOFIX_ROUNDS`` times. On final failure ``None`` is returned and
the caller falls back to a simple truncation.
"""

from __future__ import annotations

import hashlib
import logging
import os

from .chars import CHAR_CODES
from .gcal import Event

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_AUTOFIX_ROUNDS = 3
SUMMARY_CACHE_TTL_SECONDS = 30 * 24 * 3600


def event_cache_key(event: Event, max_chars: int, model: str | None = None) -> str:
    """Stable key for a Claude summary of ``event`` at the given budget.

    Keyed by account + title + start + budget + model so any meaningful
    change invalidates the cached summary automatically.
    """
    resolved_model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
    raw = "|".join(
        [
            event.account or "",
            event.title or "",
            event.start.isoformat(),
            str(max_chars),
            resolved_model,
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"vesta:claude:{digest}"

log = logging.getLogger(__name__)


OWNER_CONTEXT = (
    "The display owner is Maxim Gladkov, Co-Founder & CTO at AiQL and "
    "Founder & CTO at Sacred Graph."
)


SYSTEM_PROMPT = (
    "You turn a meeting's title into a telegraphic, at-a-glance summary"
    " for a Vestaboard Note row. Output ONE line only.\n"
    "\n"
    "HARD CONSTRAINTS - violating these breaks the board:\n"
    "- At most the character budget given in the user message.\n"
    "- ONLY these characters are allowed: A-Z, 0-9, space, and "
    "! @ # $ ( ) - + & = ; : ' \" % , . / ?\n"
    "- Uppercase only. No lowercase, no accents, no emojis, no unicode.\n"
    "- Return ONLY the summary line. No prose, no quotes, no code fences.\n"
    "\n"
    "STYLE - punchy and compressed. Drop filler words ('the', 'meeting',"
    " 'sync', 'call', 'discussion'). Abbreviate long words (REVIEW -> REV,"
    " WEEKLY -> WKLY, STANDUP -> STDUP). Join paired names with a slash"
    " (MAXIM/ADAM). Preserve proper names, company names, product names,"
    " and key numbers. Prefer clarity over cleverness.\n"
    "\n"
    "If a previous attempt failed validation, fix exactly the listed issues"
    " and return only the corrected line.\n"
)


def _format_when(event) -> str:
    import datetime as dt
    from tzlocal import get_localzone

    now_local = dt.datetime.now(get_localzone())
    local = event.start.astimezone(now_local.tzinfo)
    if local.date() == now_local.date():
        return "today (all day)" if event.all_day else f"today at {local.strftime('%H%M')}"
    delta_days = (local.date() - now_local.date()).days
    weekday = local.strftime("%A").lower()
    if delta_days == 1:
        return "tomorrow"
    if 2 <= delta_days <= 6:
        return f"this {weekday}"
    return local.strftime("%a %b %d").upper()


def _validate(text: str, max_chars: int) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    line = text.strip().splitlines()[0] if text.strip() else ""
    if "\n" in text.strip():
        errors.append("Return a single line only; do not include line breaks.")
    if len(line) > max_chars:
        errors.append(f"Summary is {len(line)} characters (max {max_chars}): {line!r}")
    bad = sorted({ch for ch in line.upper() if ch not in CHAR_CODES})
    if bad:
        errors.append(f"Summary contains unsupported characters {bad}: {line!r}")
    if not line:
        errors.append("Summary was empty.")
    if errors:
        return None, errors
    return line.upper(), []


def _format_errors(errors: list[str]) -> str:
    numbered = "\n".join(f"- {e}" for e in errors)
    return (
        "Your previous summary failed validation:\n"
        f"{numbered}\n\n"
        "Output a corrected summary following ALL the HARD CONSTRAINTS. "
        "Return only the single summary line."
    )


def _extract_text(resp) -> str:
    out = ""
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            out += getattr(block, "text", "")
    return out.strip()


def summarize_title(
    event: Event,
    max_chars: int = 15,
    model: str | None = None,
    api_key: str | None = None,
) -> str | None:
    """Return a Vestaboard-safe, uppercase summary of ``event`` or None."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.info("ANTHROPIC_API_KEY not set; skipping Claude summary")
        return None

    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed; skipping Claude summary")
        return None

    account = f" [{event.account}]" if event.account else ""
    user_msg = (
        f"{OWNER_CONTEXT}\n"
        "\n"
        f"Meeting to summarize:\n"
        f'  title: "{event.title}"{account}\n'
        f"  when:  {_format_when(event)}\n"
        "\n"
        f"Character budget for the summary: {max_chars} characters.\n"
        "Return only the summary line."
    )
    log.info("claude summary request:\n%s", user_msg)

    client = anthropic.Anthropic(api_key=api_key)
    resolved_model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
    messages: list[dict] = [{"role": "user", "content": user_msg}]

    total_attempts = 1 + MAX_AUTOFIX_ROUNDS
    for attempt in range(1, total_attempts + 1):
        try:
            resp = client.messages.create(
                model=resolved_model,
                max_tokens=60,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
        except Exception as exc:
            log.warning("claude call failed on attempt %d: %s", attempt, exc)
            return None

        text = _extract_text(resp)
        log.info("claude summary attempt %d raw output: %r", attempt, text)

        summary, errors = _validate(text, max_chars)
        if summary is not None:
            if attempt > 1:
                log.info("claude self-corrected on attempt %d", attempt)
            return summary

        log.warning("claude attempt %d failed validation: %s", attempt, errors)

        if attempt == total_attempts:
            log.warning("claude exhausted autofix budget (%d attempts)", total_attempts)
            return None

        messages.append({"role": "assistant", "content": text or "(empty)"})
        messages.append({"role": "user", "content": _format_errors(errors)})

    return None


__all__ = ["summarize_title"]

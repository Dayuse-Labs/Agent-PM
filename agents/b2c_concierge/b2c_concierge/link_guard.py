"""Deterministic hotel-link truthfulness guard (S-G12 — the 13th guard).

Why it exists (Fabien, prod repro 2026-07-24): asked for links, the synthesis
LLM fabricated `dayuse.com/hotels/france/ibis-rungis-a-roport-paris-orly` —
domain, accents and hyphenation all wrong — by slugifying the display name.
The ground-truth block now carries each hotel's REAL page url (built from the
ES slug, b2c_common.hotel_urls) and instructs the model to copy it verbatim;
this guard is the deterministic backstop for when it constructs one anyway.

Pure function, same contract as the other guards: one bounded pass over the
approved synthesis text, correction in code, never a retry loop. Any
`dayuse*/hotels/...` URL not EXACTLY in the allowed set (the urls the model
was grounded in this turn) is removed — a markdown link keeps its label, a
bare URL is excised together with its leading spaces (sentence punctuation
survives, including French space-before-colon). A modified/"translated" URL
is a fabricated URL: there is no repair path, repairing is how invented
slugs happen. Non-hotel Dayuse links (FAQ/policy pages, the booking tunnel)
never match the `/hotels/` path and pass through untouched.
"""
from __future__ import annotations

import re

# A hotel-page URL on any Dayuse host: the `/hotels/` path segment is the
# discriminator (policy pages and the booking tunnel never use it). Split on
# whitespace/brackets/quotes so a markdown `](...)` terminates the match.
_URL_PATTERN = (
    r"https?://[^\s<>()\[\]{}\"']*\bdayuse[^\s<>()\[\]{}\"']*/hotels/[^\s<>()\[\]{}\"']+"
)
# Bare form: leading spaces are part of the excision so "Voici : <url>."
# collapses to "Voici :." — never a global punctuation rewrite, which would
# mangle legitimate French spacing elsewhere in the message.
_BARE_RE = re.compile(r"([ \t]*)(" + _URL_PATTERN + r")", re.IGNORECASE)
_MARKDOWN_RE = re.compile(r"\[([^\]\n]*)\]\(\s*(" + _URL_PATTERN + r")\s*\)", re.IGNORECASE)
_TRAILING_PUNCT = ".,;:!?…"


def _canonical(url: str) -> str:
    return url.rstrip(_TRAILING_PUNCT).rstrip("/")


def _allowed_urls(hotels: list[dict] | None) -> set[str]:
    return {
        _canonical(str(h["url"]))
        for h in hotels or []
        if isinstance(h, dict) and isinstance(h.get("url"), str)
    }


def enforce_hotel_link_truthfulness(text: str, hotels: list[dict] | None) -> tuple[str, int]:
    """`(corrected_text, removed_count)` — strips every Dayuse hotel-page URL
    not grounded in this turn's shortlist. `hotels` is the SAME list the
    ground-truth block rendered (shortlist_hotels), so the model can only
    ever emit a url it was actually shown."""
    allowed = _allowed_urls(hotels)
    removed = 0

    # Markdown links first: `[label](bad-url)` collapses to `label` — running
    # the bare-URL pass alone would leave a dangling `[label]()`.
    def _markdown(match: re.Match[str]) -> str:
        nonlocal removed
        label, url = match.group(1), match.group(2)
        if _canonical(url) in allowed:
            return match.group(0)
        removed += 1
        return label

    def _bare(match: re.Match[str]) -> str:
        nonlocal removed
        url = match.group(2)
        if _canonical(url) in allowed:
            return match.group(0)
        removed += 1
        # The URL match itself may have swallowed the sentence's own final
        # punctuation ("<url>." ) — give it back.
        return url[len(url.rstrip(_TRAILING_PUNCT)):]

    corrected = _MARKDOWN_RE.sub(_markdown, text)
    corrected = _BARE_RE.sub(_bare, corrected)
    if removed:
        corrected = re.sub(r"\(\s*\)|\[\s*\]", "", corrected)
        corrected = re.sub(r"[ \t]{2,}", " ", corrected)
    return corrected, removed

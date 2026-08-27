"""Deterministic currency-disclosure guard (UX3 phase 2B, 2026-08-27).

Why it exists. S-G7 already builds a CURRENCY note whenever a shown hotel's
own `currency_code` (or the user's `profile.currency`) differs from EUR, and
instructs the synthesis LLM to "mention plainly that prices are shown in EUR
with no conversion applied" (agent.py's system prompt, point 9). That
instruction is proven UNRELIABLE: a live prod probe (`x-dayuse-synthetic:
1`, Bangkok search, 2026-08-27) showed 5 THB hotels on screen and zero
currency mention in the reply. `reports/RESEARCH-UX3-DEVISE-LOCALE-2026-08-27.md`
confirmed the same day that `priceEuro` really is EUR — so a silent turn is
a silent lie about the currency, exactly the class of defect `amenity_guard`
and `link_guard` exist to close for other claims.

Same contract as those two guards: a pure, deterministic post-LLM pass, one
bounded correction in code, never a retry. Detection of "already disclosed"
is deliberately coarse and biased toward re-stating: a false negative here
only costs one extra honest sentence, a false positive would silently drop
the disclosure — the wrong direction to err in on a price.

Deliberately NOT wired into `GUARD_SCORE_NAMES` / `budget.fired` — the 13
guards there are a counted, frozen contract (CLAUDE.md, OBS3). This is a
smaller fix than that decision deserves; flagged in the PR for Fabien to
turn into a 14th scored guard if he wants prod-measurable firing evidence.
"""
from __future__ import annotations

import re

_DISCLOSURE_TEXT = {
    "fr": "Prix affichés en euros, sans conversion.",
    "en": "Prices are shown in EUR, with no conversion applied.",
}

# Coarse on purpose (see module docstring): only skip the append when the
# model's own text already pairs a EUR/euro mention with a conversion word,
# or uses one of the stock disclosure phrases outright.
_ALREADY_DISCLOSED_RE = re.compile(
    r"\b(eur|euros?)\b[^.!?\n]{0,60}\b(conversion|converti[es]?|convert(?:ed|ing)?)\b"
    r"|\b(sans conversion|no conversion|not converted)\b",
    re.IGNORECASE,
)


def enforce_currency_disclosure(text: str, currency_note: str, language: str) -> tuple[str, bool]:
    """`(corrected_text, appended)`. `currency_note` is the same non-empty-
    when-relevant string `_synthesize_with_guards` already builds — this
    function does not re-derive it, so the two can never disagree on WHEN to
    disclose, only on whether the LLM already did."""
    if not currency_note or not text:
        return text, False
    if _ALREADY_DISCLOSED_RE.search(text):
        return text, False
    line = _DISCLOSURE_TEXT.get(language, _DISCLOSURE_TEXT["en"])
    return f"{text.rstrip()}\n\n{line}", True

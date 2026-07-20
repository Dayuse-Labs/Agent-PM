"""Post-LLM amenity claim verifier (S07), ported from agent-usa's
`AgentOrchestrator._amenity_claim_violations`/`_hedge_amenity_claims`/
`_apply_amenity_truthfulness` (`src/application/agent/orchestrator.py`) —
BEHAVIOR ported, not code: agent-usa mutates a long-lived
`Conversation.preferences` dict through `self`/`cls` methods; this module is
plain, pure functions over the hotels used to ground THIS turn's synthesis
(ground_truth.py) and returns the updated corrections dict for the caller
(agent.py) to persist on `SessionProfile.amenity_claim_corrections`.

Why this guard exists (prod sessions 3cec10e5, 0435bd8f, 5d4ac8c2, 2026-07
reviews, ~10 sessions/day): a synthesis LLM grounded in the ground-truth
shortlist still occasionally asserts an amenity the hotel's own listing does
not back ("includes a Hot tub" on a pool-only hotel). Hedging the claim TOKEN
in place ("Hot tub (not confirmed)") keeps the message self-consistent —
appending a trailing contradiction note shipped the false claim AND its
correction in the same breath.
"""
from __future__ import annotations

import re

from .amenity_synonyms import amenity_present

# Claim patterns are limited to amenities amenity_synonyms.py can verify.
_AMENITY_CLAIM_PATTERNS: dict[str, str] = {
    "pool": r"\bpools?\b|\bpiscines?\b|\bpiscinas?\b",
    "jacuzzi": r"\bjacuzzis?\b|\bhot\s?tubs?\b|\bwhirlpools?\b|bains? à remous|hidromasaje|idromassaggio",
    "spa": r"\bspas?\b",
    "sauna": r"\bsaunas?\b|\bhammam\b|steam room",
    "gym": r"\bgym\b|\bfitness\b",
    "breakfast": r"\bbreakfasts?\b|petit[- ]d[ée]jeuner|\bdesayuno\b|\bcolazione\b",
    "pet_friendly": r"pet[- ]friendly|\bpets?\b|\bdogs?\b",
    "rooftop": r"\brooftops?\b",
    "parking": r"\bparking\b|\bvalet\b|\bparcheggio\b|aparcamiento",
    "restaurant": r"\brestaurants?\b|ristorante",
    "shuttle": r"\bshuttles?\b|\bnavettes?\b",
}

_CLAIM_NEGATION_MARKERS = (
    "no ", "not ", "n't", "without", "lacks",
    "unconfirmed", "not confirmed", "not listed",
    "non listé", "non liste", "pas de", "aucun", "sans ",
    "sin ", "senza ", "não", "unverified", "double-check",
    "can't confirm", "cannot confirm", "please verify",
    # amenity_unverified_hedge translations below — a line THIS guard already
    # hedged must never be re-flagged on a later re-scan.
    "non confirmé", "non confirme", "non confermato",
    "nicht bestätigt", "nicht bestaetigt", "niet bevestigd",
)


def _shortlist_names_lower(hotels: list[dict] | None) -> set[str]:
    """Lowercased shortlist hotel names long enough to match reliably."""
    return {
        str(h.get("name") or "").strip().lower()
        for h in hotels or []
        if isinstance(h, dict) and len(str(h.get("name") or "").strip()) >= 4
    }


def _blank_hotel_names(lines: list[str], names_lower: set[str]) -> list[str]:
    """Lowercased copies of `lines` with every shortlist name blanked (same
    length, whitespace-padded) so a hotel's own name ("Saccardi Hotel & Spa")
    never reads as an amenity claim about itself, while match offsets stay
    aligned with the original line for splicing hedges at the right spot."""
    blanked: list[str] = []
    for line in lines:
        low = line.lower()
        for name_l in names_lower:
            low = re.sub(re.escape(name_l), lambda m: " " * len(m.group(0)), low, flags=re.IGNORECASE)
        blanked.append(low)
    return blanked


def amenity_claim_violations(message: str, hotels: list[dict] | None) -> dict[str, set[str]]:
    """Amenity claims about named hotels that the data doesn't back.

    Scans each response line mentioning a known hotel name for amenity
    keywords; a claim with no negation on the line (or its continuation line)
    and no backing in the hotel's amenity list is a violation."""
    text = str(message or "")
    if not text or not hotels:
        return {}
    violations: dict[str, set[str]] = {}
    lines = text.splitlines()
    all_names_l = _shortlist_names_lower(hotels)
    blanked_lines = _blank_hotel_names(lines, all_names_l)
    for hotel in hotels:
        if not isinstance(hotel, dict):
            continue
        name = str(hotel.get("name") or "").strip()
        if len(name) < 4:
            continue
        name_l = name.lower()
        for idx, line in enumerate(lines):
            line_l = line.lower()
            if name_l not in line_l:
                continue
            # Hedges often land on the continuation line — scan the claim
            # line plus the next, UNLESS that next line starts another
            # hotel's own entry (its hedge belongs to that hotel, not this one).
            next_l = lines[idx + 1].lower() if idx + 1 < len(lines) else ""
            if any(other in next_l for other in all_names_l):
                next_l = ""
            hedge_scope = f"{line_l}\n{next_l}" if next_l else line_l
            if any(marker in hedge_scope for marker in _CLAIM_NEGATION_MARKERS):
                continue
            for key, pattern in _AMENITY_CLAIM_PATTERNS.items():
                if not re.search(pattern, blanked_lines[idx], re.IGNORECASE):
                    continue
                # The hotel's own name backs the claim ("... & Spa" IS a spa
                # product) — never "correct" it.
                if re.search(pattern, name_l, re.IGNORECASE):
                    continue
                if amenity_present(key, hotel.get("amenities")):
                    continue
                violations.setdefault(name, set()).add(key)
    return violations


def _hedge_amenity_claims(
    text: str, violations: dict[str, set[str]], hotels: list[dict] | None, hedge: str
) -> tuple[str, dict[str, set[str]]]:
    """Hedges each violating amenity token in place; returns the leftovers
    (claims whose token could not be located, appended as a note by the
    caller instead). For every violating (hotel, amenity) the matched token
    on the hotel's claim line becomes "token (hedge)" — a re-scan of the
    rewritten message then yields zero violations (idempotent)."""
    lines = text.splitlines()
    blanked = _blank_hotel_names(lines, _shortlist_names_lower(hotels))
    original_l = [line.lower() for line in lines]
    remaining: dict[str, set[str]] = {}
    edited = False
    for hotel_name, amenity_keys in sorted(violations.items()):
        name_l = hotel_name.lower()
        for key in sorted(amenity_keys):
            pattern = _AMENITY_CLAIM_PATTERNS.get(key)
            hedged = False
            if pattern:
                # Hedge EVERY line repeating the claim, not just the first.
                for idx, line_l in enumerate(original_l):
                    if name_l not in line_l:
                        continue
                    if any(marker in line_l for marker in _CLAIM_NEGATION_MARKERS):
                        continue
                    match = re.search(pattern, blanked[idx], re.IGNORECASE)
                    if not match:
                        continue
                    insert = f" ({hedge})"
                    lines[idx] = lines[idx][: match.end()] + insert + lines[idx][match.end() :]
                    blanked[idx] = blanked[idx][: match.end()] + insert.lower() + blanked[idx][match.end() :]
                    hedged = True
                    edited = True
            if not hedged:
                remaining.setdefault(hotel_name, set()).add(key)
    if not edited:
        return text, remaining
    rewritten = "\n".join(lines)
    if text.endswith("\n"):
        rewritten += "\n"
    return rewritten, remaining


# Bilingual hedge/correction text — this spine's synthesis output language is
# only ever fr/en (triage.Triage.language), unlike agent-usa's 7-language t().
_HEDGE_FR = "non confirmé"
_HEDGE_EN = "not confirmed"


def _correction_note(hotel_name: str, amenity_label: str, language: str) -> str:
    if language == "fr":
        return (
            f"⚠️ Correction : {hotel_name} ne liste pas {amenity_label} parmi ses "
            "équipements Dayuse — vérifie directement auprès de l'hôtel."
        )
    return (
        f"⚠️ Correction: {hotel_name} does not list {amenity_label} among its "
        "Dayuse amenities — please verify directly with the hotel."
    )


def apply_amenity_truthfulness(
    message: str,
    hotels: list[dict] | None,
    language: str,
    already_issued: dict[str, list[str]] | None = None,
) -> tuple[str, dict[str, list[str]]]:
    """Rewrites unsourced amenity claims in place (hedge), falling back to an
    appended note only for a claim whose token could not be located. Returns
    `(text, corrections)` — `corrections` merges `already_issued` (so a
    correction is never re-appended across turns) with any fresh violation
    found this turn; the caller persists it on `profile.amenity_claim_corrections`.
    Never raises: an internal failure returns `message` unchanged."""
    try:
        violations = amenity_claim_violations(message, hotels)
        already = {str(k): set(v or []) for k, v in (already_issued or {}).items()}
        if not violations:
            merged = {name: sorted(keys) for name, keys in already.items() if keys}
            return message, merged
        hedge = _HEDGE_FR if language == "fr" else _HEDGE_EN
        text, unhedged = _hedge_amenity_claims(str(message or ""), violations, hotels, hedge)
        notes: list[str] = []
        for hotel_name, amenity_keys in sorted(unhedged.items()):
            fresh = sorted(k for k in amenity_keys if k not in already.get(hotel_name, set()))
            if not fresh:
                continue
            label = ", ".join(fresh).replace("_", " ")
            notes.append(_correction_note(hotel_name, label, language))
        merged_sets = {name: set(keys) for name, keys in already.items()}
        for hotel_name, amenity_keys in violations.items():
            merged_sets[hotel_name] = merged_sets.get(hotel_name, set()) | amenity_keys
        merged = {name: sorted(keys) for name, keys in merged_sets.items() if keys}
        if notes:
            return text.rstrip() + "\n\n" + "\n".join(notes), merged
        return text, merged
    except Exception:  # noqa: BLE001 — never break the response path
        return message, dict(already_issued or {})

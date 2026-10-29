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


# 2026-10-29 (prod after #173, 14 replies): a claim is read in its SENTENCE,
# never in its whole line. The synthesis writes a paragraph on one line, so a
# line-wide scope tied « a pool » to every hotel the paragraph named, and the
# hedge landed once per hotel on the same word: « a pool (not confirmed) (not
# confirmed) (The Delphi Hotel) ». A sentence ends at . ! ? ; or a line break
# followed by space or the end of the text — punctuation only, no word of any
# language. « 4.5/5 » or « St.Regis » never split (no space after the dot).
_SENTENCE_END = re.compile(r"[.!?;…]+(?=\s|$)|\n")


def _sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) offsets of each sentence of `text`."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        if match.end() > start:
            spans.append((start, match.end()))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _is_question(sentence: str) -> bool:
    """A question or an offer to the user (« want a pool or parking? ») asks;
    it claims nothing about a hotel. Read from its punctuation only."""
    stripped = sentence.strip()
    return stripped.endswith("?") or stripped.startswith("¿")


def _claims(text: str, hotels: list[dict] | None) -> list[tuple[str, str, int]]:
    """(hotel name, amenity key, end offset of the claimed word) for each
    amenity word the data does not back, one entry per word.

    A word is attributed to the hotel whose name is NEAREST to it in its own
    sentence; a sentence naming no hotel, asking a question, or already
    carrying a negation / hedge claims nothing."""
    valid = [h for h in hotels or [] if isinstance(h, dict) and len(str(h.get("name") or "").strip()) >= 4]
    if not text or not valid:
        return []
    names_l = _shortlist_names_lower(valid)
    by_name = {str(h.get("name")).strip().lower(): h for h in valid}
    claims: list[tuple[str, str, int]] = []
    for start, end in _sentences(text):
        sentence = text[start:end]
        low = sentence.lower()
        if _is_question(sentence) or any(marker in low for marker in _CLAIM_NEGATION_MARKERS):
            continue
        spots = [
            (m.start(), m.end(), name_l)
            for name_l in names_l
            for m in re.finditer(re.escape(name_l), low)
        ]
        if not spots:
            continue
        blanked = _blank_hotel_names([sentence], names_l)[0]
        for key, pattern in _AMENITY_CLAIM_PATTERNS.items():
            for match in re.finditer(pattern, blanked, re.IGNORECASE):
                _s, _e, name_l = min(
                    spots,
                    key=lambda spot: spot[0] - match.end() if spot[0] >= match.end() else match.start() - spot[1],
                )
                hotel = by_name[name_l]
                # The hotel's own name backs the claim ("... & Spa" IS a spa
                # product) — never "correct" it.
                if re.search(pattern, name_l, re.IGNORECASE):
                    continue
                if amenity_present(key, hotel.get("amenities")):
                    continue
                claims.append((str(hotel.get("name")).strip(), key, start + match.end()))
    return claims


def amenity_claim_violations(message: str, hotels: list[dict] | None) -> dict[str, set[str]]:
    """Amenity claims about named hotels that the data doesn't back: an
    amenity word in a sentence naming a hotel (the nearest name owns it), with
    no negation in that sentence, no question, and no backing in that hotel's
    amenity list."""
    violations: dict[str, set[str]] = {}
    for name, key, _end in _claims(str(message or ""), hotels):
        violations.setdefault(name, set()).add(key)
    return violations


def _hedge_amenity_claims(
    text: str, violations: dict[str, set[str]], hotels: list[dict] | None, hedge: str
) -> tuple[str, dict[str, set[str]]]:
    """Hedges each violating amenity word in place, ONCE per word whatever the
    number of hotels around it; returns the claims whose word could not be
    located (appended as a note by the caller). A re-scan of the rewritten
    text yields zero violations (idempotent: the hedge is a negation marker)."""
    wanted = {(name, key) for name, keys in violations.items() for key in keys}
    claims = [c for c in _claims(text, hotels) if (c[0], c[1]) in wanted]
    located = {(name, key) for name, key, _ in claims}
    remaining: dict[str, set[str]] = {}
    for name, key in sorted(wanted - located):
        remaining.setdefault(name, set()).add(key)
    rewritten = text
    for offset in sorted({end for _, _, end in claims}, reverse=True):
        rewritten = rewritten[:offset] + f" ({hedge})" + rewritten[offset:]
    return rewritten, remaining


# Hedge/correction text for the 7 languages the spine can answer in since UX2
# (2026-08-27) — matching agent-usa's 7-language t() parity (behavior ported,
# not code, like the rest of this module — see its docstring).
_HEDGE: dict[str, str] = {
    "fr": "non confirmé",
    "en": "not confirmed",
    "es": "no confirmado",
    "it": "non confermato",
    "de": "nicht bestätigt",
    "pt": "não confirmado",
    "nl": "niet bevestigd",
}

_CORRECTION_NOTE: dict[str, str] = {
    "fr": (
        "⚠️ Correction : {hotel_name} ne liste pas {amenity_label} parmi ses "
        "équipements Dayuse — vérifie directement auprès de l'hôtel."
    ),
    "en": (
        "⚠️ Correction: {hotel_name} does not list {amenity_label} among its "
        "Dayuse amenities — please verify directly with the hotel."
    ),
    "es": (
        "⚠️ Corrección: {hotel_name} no incluye {amenity_label} entre sus "
        "servicios Dayuse — verifícalo directamente con el hotel."
    ),
    "it": (
        "⚠️ Correzione: {hotel_name} non include {amenity_label} tra i suoi "
        "servizi Dayuse — verifica direttamente con l'hotel."
    ),
    "de": (
        "⚠️ Korrektur: {hotel_name} listet {amenity_label} nicht unter seinen "
        "Dayuse-Ausstattungen — bitte direkt beim Hotel nachfragen."
    ),
    "pt": (
        "⚠️ Correção: {hotel_name} não inclui {amenity_label} entre os seus "
        "serviços Dayuse — verifique diretamente com o hotel."
    ),
    "nl": (
        "⚠️ Correctie: {hotel_name} vermeldt {amenity_label} niet bij zijn "
        "Dayuse-voorzieningen — controleer dit rechtstreeks bij het hotel."
    ),
}


def _correction_note(hotel_name: str, amenity_label: str, language: str) -> str:
    template = _CORRECTION_NOTE.get(language, _CORRECTION_NOTE["en"])
    return template.format(hotel_name=hotel_name, amenity_label=amenity_label)


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
        hedge = _HEDGE.get(language, _HEDGE["en"])
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

"""Reduce a typed party total without treating it as an adult count.

Ported from #134 (PORT1 slice 5).
"""
from __future__ import annotations


def resolve_party_update(adults: int | None, children: int | None,
                         pending_total: int | None, update: dict[str, int] | None
                         ) -> tuple[dict[str, int] | None, int | None]:
    if not update:
        return None, pending_total
    counts: dict[str, int] = {k: update[k] for k in ("adults", "children") if k in update}
    total = update.get("total", pending_total)
    if total is None:
        return counts or None, None
    # A complete new composition supersedes a previously unresolved total.
    # Contradictory counts within the same extraction are rejected upstream.
    if len(counts) == 2:
        return counts, None
    if len(counts) == 1:
        key = next(iter(counts))
        other = "children" if key == "adults" else "adults"
        remainder = total - counts[key]
        if (0 if other == "children" else 1) <= remainder <= 30:
            return {**counts, other: remainder}, None
        return counts, total
    # Prod audit 2026-11-02: one person is one adult (a child never books
    # alone) — nothing to ask, no « group of 1 » to discover.
    if total == 1:
        return {"adults": 1, "children": 0}, None
    # Repeating the known total confirms the existing composition. A DIFFERENT
    # total does not tell us whether an adult or child joined/left the group.
    if adults is not None and children is not None and adults + children == total:
        return {"adults": adults, "children": children}, None
    return None, total


def party_composition_question(total: int, language: str) -> str:
    questions = {
        "fr": "Pour ces {total} personnes, combien y a-t-il d’adultes et d’enfants ?",
        "en": "Of these {total} guests, how many are adults and how many are children?",
        "de": "Wie viele der {total} Gäste sind Erwachsene und wie viele Kinder?",
        "es": "De estas {total} personas, ¿cuántas son adultos y cuántas niños?",
        "it": "Di queste {total} persone, quanti sono adulti e quanti bambini?",
        "pt": "Destas {total} pessoas, quantas são adultos e quantas são crianças?",
        "nl": "Hoeveel van deze {total} gasten zijn volwassenen en hoeveel kinderen?",
    }
    return questions.get(language, questions["en"]).format(total=total)

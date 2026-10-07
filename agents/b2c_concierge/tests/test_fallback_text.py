"""fallback_text.py — the code-built answer served when the synthesis fails
(mcp-dayuse#8, QA trace 62207822)."""
from b2c_concierge.fallback_text import synthesis_fallback_text

LEAF = "2 offre(s) de jour trouvée(s) : A, B. Recherche effectuée pour le 2026-09-30."


def _fallback(leaf=LEAF, message="un hôtel à Lyon", language="fr", widen=None, currency_note=""):
    return synthesis_fallback_text(
        leaf, message=message, language=language, widen=widen, currency_note=currency_note
    )


def test_iso_dates_are_written_out():
    assert _fallback() == (
        "2 offre(s) de jour trouvée(s) : A, B. Recherche effectuée pour le mercredi 30 septembre 2026."
    )


def test_english_date():
    text = _fallback("2 day-use offer(s) found: A, B. Searched for 2026-09-30.", language="en")
    assert text.endswith("Searched for Wednesday, September 30, 2026.")


def test_parking_request_gets_the_unfiltered_reserve():
    assert "filtrer les résultats sur le parking" in _fallback(message="avec parking et piscine")
    assert "filter the results on parking" in _fallback(message="hotel with parking", language="en")


def test_no_parking_reserve_without_a_parking_request():
    assert "parking" not in _fallback(message="avec piscine")


def test_auto_widen_is_disclosed():
    text = _fallback(widen={"from": 100, "to": 130.0})
    assert "élargi automatiquement de 100 € à 130 €" in text


def test_currency_note_is_disclosed():
    text = _fallback(currency_note="hotel's own currency: USD")
    assert text.endswith("Prix affichés en euros, sans conversion.")


def test_empty_leaf_text_stays_empty():
    assert _fallback(leaf="  ", message="avec parking") == ""

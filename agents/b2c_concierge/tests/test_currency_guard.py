"""Currency-disclosure guard tests (UX3 phase 2B, 2026-08-27): the CURRENCY
note already reaches the prompt (S-G7, see TestCurrencyDisclosureThroughTheSpine
in test_spine_profile.py) but a live prod probe showed the LLM silently
dropping the instruction — this backstops it in code, one pass, no retry."""
from __future__ import annotations

from b2c_concierge.currency_guard import enforce_currency_disclosure

_NOTE = "hotel's own currency: THB"


class TestDisclosureAppended:
    def test_missing_disclosure_gets_appended_fr(self):
        text = "Voici 5 offres a Bangkok avec piscine."
        corrected, appended = enforce_currency_disclosure(text, _NOTE, "fr")
        assert appended is True
        assert corrected.startswith(text)
        assert "Prix affichés en euros, sans conversion." in corrected

    def test_missing_disclosure_gets_appended_en(self):
        text = "Here are 5 offers in Bangkok with a pool."
        corrected, appended = enforce_currency_disclosure(text, _NOTE, "en")
        assert appended is True
        assert "Prices are shown in EUR, with no conversion applied." in corrected

    def test_unrecognized_language_falls_back_to_english(self):
        corrected, appended = enforce_currency_disclosure("Aqui tienes 5 hoteles.", _NOTE, "es")
        assert appended is True
        assert "Prices are shown in EUR" in corrected


class TestNoOpWhenIrrelevantOrAlreadyDisclosed:
    def test_empty_currency_note_is_a_no_op(self):
        text = "Voici 5 offres a Paris."
        assert enforce_currency_disclosure(text, "", "fr") == (text, False)

    def test_empty_text_is_a_no_op(self):
        assert enforce_currency_disclosure("", _NOTE, "fr") == ("", False)

    def test_model_already_disclosing_eur_and_conversion_is_not_duplicated(self):
        text = "Voici 5 offres. Les prix sont affiches en EUR, sans conversion vers le THB."
        corrected, appended = enforce_currency_disclosure(text, _NOTE, "fr")
        assert appended is False
        assert corrected == text

    def test_model_using_the_stock_english_phrase_is_not_duplicated(self):
        text = "Here are 5 offers. No conversion has been applied to these prices."
        corrected, appended = enforce_currency_disclosure(text, _NOTE, "en")
        assert appended is False
        assert corrected == text

    def test_bare_eur_mention_without_a_conversion_word_still_gets_the_line(self):
        # "priced in EUR" alone does not say a conversion was skipped — the
        # coarse regex requires both a currency word AND a conversion word
        # (or a stock phrase) before treating the disclosure as already made.
        text = "Voici 5 offres. Le prix est en EUR."
        corrected, appended = enforce_currency_disclosure(text, _NOTE, "fr")
        assert appended is True
        assert "sans conversion" in corrected.lower()

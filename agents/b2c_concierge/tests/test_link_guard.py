"""Link truthfulness guard tests (S-G12, guard #13): any Dayuse hotel-page
URL the synthesis was not grounded in is stripped in code — one pass, no
retry. Locks the prod fabrication shape (name-slugified URL on the wrong
domain) and the pass-through of legitimate non-hotel Dayuse links."""
from __future__ import annotations

from b2c_concierge.link_guard import enforce_hotel_link_truthfulness

_GOOD = "https://www.dayuse.fr/hotels/france/ibis-rungis-aeroport-paris-orly"
_HOTELS = [{"name": "Ibis Rungis", "url": _GOOD}]


class TestGroundedLinksPass:
    def test_exact_shortlist_url_is_kept(self):
        text = f"Voici le lien : {_GOOD}"
        assert enforce_hotel_link_truthfulness(text, _HOTELS) == (text, 0)

    def test_trailing_slash_and_sentence_punctuation_tolerated(self):
        text = f"Réservez ici : {_GOOD}/."
        corrected, removed = enforce_hotel_link_truthfulness(text, _HOTELS)
        assert removed == 0
        assert corrected == text

    def test_grounded_markdown_link_is_kept_whole(self):
        text = f"[Ibis Rungis]({_GOOD})"
        assert enforce_hotel_link_truthfulness(text, _HOTELS) == (text, 0)


class TestFabricatedLinksStripped:
    def test_prod_repro_name_slugified_url_is_removed(self):
        # The exact 2026-07-24 fabrication: wrong domain + é mangled to a hyphen.
        text = (
            "Voici : https://www.dayuse.com/hotels/france/ibis-rungis-a-roport-paris-orly."
        )
        corrected, removed = enforce_hotel_link_truthfulness(text, _HOTELS)
        assert removed == 1
        assert "dayuse.com" not in corrected
        assert corrected == "Voici :."  # URL gone, sentence punctuation kept

    def test_markdown_fabrication_keeps_its_label(self):
        text = "Réservez [Eurohotel](https://www.dayuse.com/hotels/france/eurohotel-airport) !"
        corrected, removed = enforce_hotel_link_truthfulness(text, _HOTELS)
        assert removed == 1
        assert corrected == "Réservez Eurohotel !"

    def test_modified_grounded_url_counts_as_fabricated(self):
        text = _GOOD.replace("aeroport", "airport")
        corrected, removed = enforce_hotel_link_truthfulness(f"Lien : {text}", _HOTELS)
        assert removed == 1
        assert "airport" not in corrected

    def test_empty_shortlist_strips_every_hotel_link(self):
        corrected, removed = enforce_hotel_link_truthfulness(f"Voir {_GOOD}", [])
        assert removed == 1
        assert "dayuse" not in corrected

    def test_multiple_fabrications_all_counted(self):
        text = (
            "https://www.dayuse.com/hotels/france/a et "
            "https://www.dayuse.com/hotels/france/b"
        )
        corrected, removed = enforce_hotel_link_truthfulness(text, _HOTELS)
        assert removed == 2
        assert "dayuse" not in corrected


class TestNonHotelLinksUntouched:
    def test_booking_tunnel_and_policy_links_pass_through(self):
        text = (
            "Payez sur https://www.dayuse.fr/tunnel/booking?offerId=abc et lisez "
            "https://www.dayuse.com/help/cancellation"
        )
        assert enforce_hotel_link_truthfulness(text, _HOTELS) == (text, 0)

    def test_photo_host_hotel_paths_are_not_exempt(self):
        # static.dayuse.com/hotels/... never legitimately appears in prose —
        # an ungrounded one is stripped like any other hotel-path URL.
        corrected, removed = enforce_hotel_link_truthfulness(
            "Photo : https://static.dayuse.com/hotels/1/x.png", _HOTELS
        )
        assert removed == 1
        assert "static.dayuse.com" not in corrected

    def test_non_dayuse_urls_are_left_alone(self):
        text = "Voir https://example.com/hotels/france/whatever"
        assert enforce_hotel_link_truthfulness(text, _HOTELS) == (text, 0)


class TestRobustness:
    def test_hotels_without_urls_and_garbage_entries_are_tolerated(self):
        corrected, removed = enforce_hotel_link_truthfulness(
            f"Voir {_GOOD}", [{"name": "No url"}, "garbage", None]
        )
        assert removed == 1

    def test_plain_text_is_returned_verbatim(self):
        text = "Aucun lien ici, juste du texte avec dayuse.com mentionné sans URL."
        assert enforce_hotel_link_truthfulness(text, _HOTELS) == (text, 0)

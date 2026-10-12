"""The market referential is hand-kept in Python AND in JS — this is the guard.

UX6 audit option C, arbitrated by Fabien 2026-08-28
(`reports/AUDIT-MAPPINGS-2026-08-28.md` §6.3). It does NOT unify the tables —
that is its own phase. It removes the SILENT failure, which is the only risk
the audit could actually quantify:

`libs/b2c_common/b2c_common/hotel_urls.py:8-10` records the incident this is
about — agent-usa shipped a 4-day 404 outage because two hand-kept host lists
drifted apart. The lesson was applied between the two Python callers (one
`_MARKET`) and never across the back/front boundary. Measured 2026-08-28: the
country sets and the country-path slugs agreed, but nothing made them keep
agreeing, and a market added to `_MARKET` with a genuinely new eTLD would be
rejected by the widget's own host allowlist with no test to say so.

Since UX6 also removed the widget's name-slugifying fallback, a rejected host
no longer yields a WRONG link — it yields NO link. Better, still silent. Hence
this file.

Offline: parses the committed JS literals, imports the Python table. No node,
no network. The parsers are imported from `scripts/measure_market_table_drift.py`
rather than re-implemented — re-implementing them here would have made this
test a FIFTH hand-kept copy of the thing it exists to police.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

from b2c_common.hotel_urls import _MARKET

REPO_ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_market_table_drift.py"
_spec = importlib.util.spec_from_file_location("measure_market_table_drift", _SCRIPT)
assert _spec is not None and _spec.loader is not None
drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drift)


@pytest.fixture(scope="module")
def country_meta() -> dict[str, dict[str, str]]:
    return drift._country_meta()


@pytest.fixture(scope="module")
def dayuse_hosts() -> list[str]:
    return drift._dayuse_hosts()


@pytest.fixture(scope="module")
def slug_to_code() -> dict[str, str]:
    return drift._slug_to_code()


class TestTheParsersActuallyParsed:
    """A parser that silently returns {} would make every assertion below pass.

    This is the same failure mode as the `_old_dedup_count` false positive in
    `probe_rateplan_dedup.py` (HANDOFF 2026-08-27 nonies): a measurement that
    reads nothing reads exactly like a measurement that found nothing.
    """

    def test_the_python_table_is_not_empty(self) -> None:
        assert len(_MARKET) >= 20

    def test_country_meta_parsed(self, country_meta: dict[str, dict[str, str]]) -> None:
        assert len(country_meta) >= 20
        assert country_meta["FR"]["hotelCountrySlug"] == "france"

    def test_dayuse_hosts_parsed(self, dayuse_hosts: list[str]) -> None:
        assert len(dayuse_hosts) >= 10
        assert "dayuse.fr" in dayuse_hosts

    def test_slug_table_parsed(self, slug_to_code: dict[str, str]) -> None:
        assert len(slug_to_code) >= 20
        assert slug_to_code["france"] == "FR"


class TestHostAllowlistStillAdmitsEveryMarket:
    """THE regression this file exists for: a market whose booking host the
    widget's sanitizer rejects loses its hotel-page link entirely."""

    def test_every_market_host_passes_the_widget_allowlist(
        self, dayuse_hosts: list[str]
    ) -> None:
        rejected = {
            code: host
            for code, (host, _slug) in _MARKET.items()
            if not drift._host_allowed(host, dayuse_hosts)
        }
        assert rejected == {}, (
            f"{len(rejected)} market host(s) would be REJECTED by DAYUSE_HOSTS in "
            f"web/vendor/static/js/chat/security.js: {rejected}. Every hotel card in "
            "those markets renders with no hotel-page link. Add the host root there."
        )

    def test_the_allowlist_check_can_actually_fail(self, dayuse_hosts: list[str]) -> None:
        """Without this, the test above could be vacuously green."""
        assert not drift._host_allowed("www.dayuse.pl", dayuse_hosts)
        assert drift._host_allowed("www.dayuse.fr", dayuse_hosts)
        # The subdomain rule is why th./au./ca./nz./my./pt. markets pass today.
        assert drift._host_allowed("th.dayuse.com", dayuse_hosts)


class TestCountryPathSlugsAgree:
    """`_MARKET`'s slug builds the backend booking URL; `COUNTRY_META`'s builds
    the widget's browse URL. A divergence sends the two to different pages."""

    def test_every_market_slug_matches_the_widget(
        self, country_meta: dict[str, dict[str, str]]
    ) -> None:
        by_code = {meta["code"]: meta for meta in country_meta.values()}
        drifted = {
            code: (py_slug, by_code.get(code, {}).get("hotelCountrySlug"))
            for code, (_host, py_slug) in _MARKET.items()
            if by_code.get(code, {}).get("hotelCountrySlug") != py_slug
        }
        assert drifted == {}, (
            "country-path slug drift between _MARKET (hotel_urls.py) and "
            f"COUNTRY_META (markets.js), {{code: (python, js)}}: {drifted}"
        )

    def test_the_country_sets_match(self, country_meta: dict[str, dict[str, str]]) -> None:
        js_codes = {meta["code"] for meta in country_meta.values()}
        assert set(_MARKET) == js_codes, (
            f"only in _MARKET: {sorted(set(_MARKET) - js_codes)}; "
            f"only in COUNTRY_META: {sorted(js_codes - set(_MARKET))}"
        )

    def test_every_market_slug_is_reverse_mapped(self, slug_to_code: dict[str, str]) -> None:
        """`inferCountryCodeFromUrl` reads the market back OUT of a hotel URL
        path, so the reverse table must cover what the backend emits."""
        unmapped = {
            slug: code for code, (_host, slug) in _MARKET.items() if slug not in slug_to_code
        }
        assert unmapped == {}, (
            f"slugs the backend emits that COUNTRY_SLUG_TO_CODE cannot read back: {unmapped}"
        )


class TestKnownDivergenceIsNotAsserted:
    """Documented, deliberately NOT failed: 8/22 browse-URL hosts differ from
    the booking hosts (AE AU BR CA HK MY NZ TH all browse on www.dayuse.com).

    That is a product question — whether a browse link should live on the
    market host — not a silent breakage, so this file does not gate it. Locking
    it in either direction would be deciding it. Recorded here so the next
    reader knows it was measured and left alone (audit §6.1).
    """

    def test_browse_host_divergence_is_measured_not_gated(
        self, country_meta: dict[str, dict[str, str]]
    ) -> None:
        from urllib.parse import urlparse

        by_code = {meta["code"]: meta for meta in country_meta.values()}
        divergent = {
            code
            for code, (py_host, _slug) in _MARKET.items()
            if urlparse(by_code[code]["browseUrl"]).hostname != py_host
        }
        # Asserted as a COUNT, not a set membership: this is a tripwire on the
        # scale of the divergence, so an unnoticed drift in a NEW market still
        # shows up, without pretending the current 8 are a bug.
        assert len(divergent) <= 8, (
            f"browse-host divergence grew beyond the 8 markets measured on "
            f"2026-08-28: {sorted(divergent)}"
        )


class TestGeneratedFileIsCurrent:
    """UX6 option B: the widget's market tables are GENERATED from `_MARKET` /
    `_BROWSE_PATH` / `_LABEL`, so they cannot drift from the Python referential
    unless someone edits the artifact or forgets to regenerate. This is the gate
    that makes that impossible rather than merely discouraged.

    This is why the slug/set comparisons above are now near-tautological — kept
    anyway, because they fail LOUDLY and specifically if the generator is ever
    changed to stop deriving one of those fields.
    """

    def test_committed_artifact_matches_the_python_referential(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_widget_markets.py"
        spec = importlib.util.spec_from_file_location("generate_widget_markets", script)
        assert spec is not None and spec.loader is not None
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)

        target = REPO_ROOT / "web" / "vendor" / "static" / "js" / "chat" / "markets.generated.js"
        assert target.is_file(), f"missing generated file: {target}"
        assert target.read_text(encoding="utf-8") == gen.render(), (
            "web/vendor/static/js/chat/markets.generated.js is STALE or was hand-edited.\n"
            "Fix: .venv/bin/python scripts/generate_widget_markets.py\n"
            "Never edit the generated file — change the Python table in "
            "libs/b2c_common/b2c_common/hotel_urls.py instead."
        )

    def test_the_market_with_no_browse_page_is_null_not_guessed(self) -> None:
        """MY has no browse page in dayuse-com's own config and
        `www.dayuse.com/s/malaysia` is a measured 404 — so the referential must
        carry None and the widget must render no link, never a guess."""
        from b2c_common.hotel_urls import market_referential

        rows = {row["iso"]: row for row in market_referential()}
        assert rows["MY"]["browse_url"] is None
        assert rows["MY"]["host"] == "my.dayuse.com"  # the BOOKING host still exists
        # And a market that does have one is a real per-market host, not the
        # global one the widget used to send everybody to.
        assert rows["TH"]["browse_url"] == "https://th.dayuse.com/s/thailand"
        assert rows["BR"]["browse_url"] == "https://www.dayuse.net.br/s/brasil"

    def test_the_three_markets_added_for_live_unmapped_inventory(self) -> None:
        """2026-08-28: KR/TR/QA had live MCP inventory while unmapped, so their
        cards carried NO link (before #109 removed the fabricator, they carried a
        wrong invented one). Host + country path verified against a real hotel
        URL per market, and all 15 real MCP hotels resolved 200.

        QA uses `qa.dayuse.com`, not the `www.dayuse.com` of the sample URL:
        both serve the page, but the SAME hotel reads `"currency":"USD"` on www
        and `"currency":"QAR"` on qa. Locking that in — reverting it to www would
        silently price Qatari hotels in dollars.
        """
        from b2c_common.hotel_urls import build_hotel_page_url

        assert build_hotel_page_url("hotel-nafore", None, "South Korea") == (
            "https://kr.dayuse.com/hotels/south-korea/hotel-nafore"
        )
        assert build_hotel_page_url("mavirem-hotel", None, "Turkey") == (
            "https://tr.dayuse.com/hotels/turkey/mavirem-hotel"
        )
        assert build_hotel_page_url("ibis-doha", None, "Qatar") == (
            "https://qa.dayuse.com/hotels/qatar/ibis-doha"
        )
        # The name leg is what actually fires in prod: search_offers sends
        # countryName and never a countryCode (0/201 measured).
        assert build_hotel_page_url("ibis-doha", "QA", None) == (
            "https://qa.dayuse.com/hotels/qatar/ibis-doha"
        )
        # "Türkiye" folds to "turkiye"; both spellings must resolve.
        assert build_hotel_page_url("mavirem-hotel", None, "Türkiye") == (
            "https://tr.dayuse.com/hotels/turkey/mavirem-hotel"
        )

    def test_korea_is_the_only_browse_path_carrying_a_city(self) -> None:
        """dayuse-com's `defaultSearchPageLink` for ko-KR is "south-korea/seoul",
        the only market entry with a city in it — and it is where the whole KR
        inventory is (2 hotels, both Seoul). Asserted so a future "cleanup" that
        strips it to "south-korea" has to be a deliberate decision."""
        from b2c_common.hotel_urls import market_referential

        rows = {row["iso"]: row for row in market_referential()}
        assert rows["KR"]["browse_url"] == "https://kr.dayuse.com/s/south-korea/seoul"
        with_city = [
            iso for iso, row in rows.items()
            if row["browse_url"] and str(row["browse_url"]).count("/") > 4
        ]
        assert with_city == ["KR"], f"a second market gained a city segment: {with_city}"

    def test_browse_paths_are_localized_where_dayuse_com_says_so(self) -> None:
        """The trap that kept these two tables apart: the browse segment is
        LOCALIZED while the hotel path is English, so neither can be derived
        from the other. Values from dayuse-com's per-locale configs, 2026-08-28.
        """
        from b2c_common.hotel_urls import market_referential

        rows = {row["iso"]: row for row in market_referential()}
        for iso, hotel_path, browse_segment in (
            ("DE", "germany", "deutschland"),
            ("BR", "brazil", "brasil"),
            ("ES", "spain", "espana"),
            ("IT", "italy", "italia"),
            ("NL", "netherlands", "nederland"),
            ("CH", "switzerland", "suisse"),
        ):
            assert rows[iso]["country_path"] == hotel_path
            assert str(rows[iso]["browse_url"]).endswith(f"/s/{browse_segment}")


class TestWidgetUrlContract:
    """Runs `tests/widget/widget_url_contract.test.mjs` — the JS half of UX6's
    arbitrated fixes (the widget must not invent a hotel URL).

    Wired through pytest rather than a new CI job on purpose: `pytest -q` is
    this repo's single gate (CLAUDE.md), and node ships on GitHub's
    ubuntu-latest runner, so no workflow change is needed. Offline: the .mjs
    imports local files only.
    """

    def test_the_widget_never_fabricates_a_hotel_url(self) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not installed — JS contract unverified in this environment")
        suite = REPO_ROOT / "tests" / "widget" / "widget_url_contract.test.mjs"
        assert suite.is_file(), f"missing JS suite: {suite}"
        # Every widget suite of the directory rides the same gate (mcp-dayuse#6
        # added the session-expiry one).
        suites = sorted(str(path) for path in suite.parent.glob("*.test.mjs"))
        result = subprocess.run(
            [node, "--test", *suites],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            "widget URL contract broken — see reports/AUDIT-MAPPINGS-2026-08-28.md §6.2\n"
            f"{result.stdout}\n{result.stderr}"
        )

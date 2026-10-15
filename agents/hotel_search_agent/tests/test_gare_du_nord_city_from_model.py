"""QA14707 Q25 (DQ12): a bare « Gare du Nord » searches Paris, so what the leaf's
model reads no longer tells it to leave the city null for places that exist in
several cities.

The declaration (`Place.city`) and the leaf instruction used to cite « Gare du
Nord » (Paris, Brussels) as a null case: the model then gave no city and the
bare-landmark branch asked the user which one. DQ6 gives homonyms to the
geocoder; the only LLM-side city rule left is S5 (« gare de Lyon »).

This proves what the model READS and what the code does with a null city, not
what the model writes: that is H3'.
"""
from __future__ import annotations

from typing import Any

from google.adk.models.lite_llm import _function_declaration_to_tool_param
from google.adk.tools.function_tool import FunctionTool

from hotel_search_agent.agent import INSTRUCTION
from hotel_search_agent.geocode_tool import geocode_location


def _city_description() -> str:
    declaration = FunctionTool(geocode_location)._get_declaration()
    assert declaration is not None
    param: dict[str, Any] = _function_declaration_to_tool_param(declaration)
    defs = param["function"]["parameters"]["$defs"]
    return defs["Place"]["properties"]["city"]["description"]


class TestDeclaration:
    def test_no_gare_du_nord_and_no_several_cities_null_case(self):
        city = _city_description()
        assert "Gare du Nord" not in city
        assert "several cities" not in city

    def test_the_s5_and_city_place_null_cases_stay(self):
        city = _city_description()
        assert '"gare de Lyon"' in city
        assert "the place is itself a city" in city

    def test_homonyms_belong_to_the_tool(self):
        assert "decided by the tool" in _city_description()

    def test_positive_examples_stay(self):
        city = _city_description()
        for example in ("Buckingham Palace", "le Louvre", "times square"):
            assert example in city


class TestLeafInstruction:
    def test_no_several_cities_null_case(self):
        flat = " ".join(INSTRUCTION.split())
        assert "exist in several cities" not in flat
        assert '("Gare du Nord": Paris, Brussels)' not in flat
        assert "the tool then asks the user which city" not in flat

    def test_homonyms_belong_to_the_tool(self):
        flat = " ".join(INSTRUCTION.split())
        assert "Homonyms are decided by the tool (the geocoder), not by you." in flat

    def test_s5_bullet_stays(self):
        flat = " ".join(INSTRUCTION.split())
        assert "A place NAMED AFTER A CITY IT IS NOT IN" in flat
        s5 = flat.index("NAMED AFTER A CITY IT IS NOT IN")
        assert '`ambiguity.reason` to "city_needed" and give no city' in flat[s5:s5 + 400]
        assert "the tool asks the user which one" in flat[s5:s5 + 600]

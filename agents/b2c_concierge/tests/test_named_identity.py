import pytest
from b2c_common.named_identity import named_identity_grounded


@pytest.mark.parametrize("query,name,city,expected", [
    ("Hôtel Étoile", "Hotel Etoile Centre", "Paris", True),
    ("DoubleTree Canton", "DoubleTree by Hilton Canton Downtown", "Canton", True),
    ("Maritime", "Maritime Hotel", "Fort Lauderdale", True),
    ("Bayview", "Bellevue Grand Hotel", "Seattle", False),
    ("Paris", "Hotel Paris Opera", "Paris", False),
    ("Bayview London", "Bayview Hotel", "Paris", False),
    (None, "Example", None, False),
    ("", "Example", None, False),
])
def test_catalog_identity_requires_customer_words(query, name, city, expected):
    assert named_identity_grounded(query, {"name": name, "cityName": city}) is expected

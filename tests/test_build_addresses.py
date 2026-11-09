"""Building the address index: the rules, on addresses as the map has them (no map needed)."""

import importlib.util
import pathlib

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "build_addresses.py"


@pytest.fixture
def build():
    pytest.importorskip("osmium")
    spec = importlib.util.spec_from_file_location("build_addresses", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_streets_are_written_as_they_are_looked_up(build):
    assert build.street_key("W. 85th St") == "west 85th street"
    assert build.street_key("Saint John's Pl") == "saint johns place"
    assert build.street_key("Central Park West") == "central park west"


def test_house_numbers_have_a_value_except_ranges(build):
    assert [build.house_value(n) for n in ("715", "85b", "144-176")] == [715, 85, None]


def test_an_address_is_kept_once_in_the_two_boroughs_at_the_average_of_its_places(build):
    rows = build.rows([
        ("715", "58th Street", "11220", 40.60, -74.00), ("715", "58th St", "11220-1234", 40.62, -74.02),  # twice
        ("85B", "W 85th St", "10024", 40.78, -73.97),
        ("1", "Main St", "12207", 40.70, -73.95),  # another zip code
        ("177", "Sarles Lane", "11211", 41.13, -73.79),  # a Brooklyn zip code, 50 km north
        ("", "No Number St", "11220", 40.60, -74.00),
    ])
    assert rows[0][:6] == ("715", 715, "58th street", "58th Street", "Brooklyn", "11220")
    assert rows[0][6:] == pytest.approx((40.61, -74.01))
    assert rows[1][:6] == ("85b", 85, "west 85th street", "W 85th St", "Manhattan", "10024")
    assert len(rows) == 2

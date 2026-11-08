"""Finding addresses, in a small address index made for each test."""

import sqlite3

import pytest

from homecare.addresses import AddressError, find, ordinal

ROWS = [
    ("6502", 6502, "18th avenue", "18th Avenue", "Brooklyn", "11204", 40.619, -73.990),
    ("715", 715, "58th street", "58th Street", "Brooklyn", "11220", 40.638, -74.008),
    ("716", 716, "58th street", "58th Street", "Brooklyn", "11220", 40.638, -74.008),
    ("719", 719, "58th street", "58th Street", "Brooklyn", "11220", 40.638, -74.008),
    ("801", 801, "58th street", "58th Street", "Brooklyn", "11220", 40.637, -74.007),
    ("6402", 6402, "bay parkway", "Bay Parkway", "Brooklyn", "11204", 40.616, -73.982),
    ("201", 201, "east 14th street", "East 14th Street", "Manhattan", "10003", 40.733, -73.987),
    ("1200", 1200, "broadway", "Broadway", "Brooklyn", "11221", 40.694, -73.931),
    ("1200", 1200, "broadway", "Broadway", "Manhattan", "10001", 40.746, -73.988),
]


@pytest.fixture
def index(tmp_path):
    path = tmp_path / "addresses.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE addresses (number TEXT, number_value INTEGER, street TEXT, display TEXT, "
               "borough TEXT, zip TEXT, lat REAL, lon REAL)")
    db.executemany("INSERT INTO addresses VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ROWS)
    db.commit()
    db.close()
    return path


def test_short_forms_and_any_case_are_understood(index):
    assert find("6502 18th Ave, Brooklyn", index).display == "6502 18th Avenue, Brooklyn 11204"
    assert find("6502 18TH AVE., brooklyn", index).display == "6502 18th Avenue, Brooklyn 11204"
    assert find("6402 Bay Pkwy", index).display == "6402 Bay Parkway, Brooklyn 11204"
    assert find("201 E 14th St, Manhattan, NY 10003", index).display == "201 East 14th Street, Manhattan 10003"


def test_a_found_address_has_its_place_on_the_map(index):
    place = find("6502 18th Ave, Brooklyn", index)
    assert (place.lat, place.lon) == (40.619, -73.990)


def test_a_street_not_in_the_index(index):
    with pytest.raises(AddressError, match='not found: no street called "19th avenue".*; check how the street is '
                                           'written: write it as house number, street name with its type'):
        find("6502 19th Ave, Brooklyn", index)


def test_a_house_number_not_on_the_street(index):
    with pytest.raises(AddressError, match="not found: 18th Avenue in Brooklyn has no number 9999, nor one near"):
        find("9999 18th Ave, Brooklyn", index)


def test_a_street_in_both_boroughs_needs_the_borough(index):
    with pytest.raises(AddressError, match="unclear: 1200 Broadway is in both Brooklyn and Manhattan"):
        find("1200 Broadway", index)
    assert find("1200 Broadway, Manhattan", index).display == "1200 Broadway, Manhattan 10001"


def test_text_without_a_house_number_is_refused(index):
    with pytest.raises(AddressError, match='could not read "Brooklyn"'):
        find("Brooklyn", index)


def test_for_a_number_the_street_hasnt_the_nearest_on_the_same_side_is_used_and_said(index):
    # 58th St has 715, 716 and 719 (and 801, too far to be nearby): 717 is between 715 and 719; the lower is used.
    place = find("717 58th St, Brooklyn", index)
    assert place.display == "715 58th Street, Brooklyn 11220"
    assert place.note == "717 isn't on 58th Street; 715, the nearest on the same side, is used"
    assert find("721 58th St, Brooklyn", index).display.startswith("719 ")
    assert find("715 58th St, Brooklyn", index).note == ""  # found as asked
    with pytest.raises(AddressError, match="has no number 900, nor one near it on the same side of the street"):
        find("900 58th St, Brooklyn", index)


def test_a_wrong_ending_on_a_street_number_and_new_yorkers_short_boroughs_are_read(index):
    assert find("715 58nd st, bk", index).display == "715 58th Street, Brooklyn 11220"
    assert find("715 58th st. bk", index).display == "715 58th Street, Brooklyn 11220"  # no comma before bk
    assert find("715 58TH ST, Bklyn NY", index).display == "715 58th Street, Brooklyn 11220"
    assert [ordinal(w) for w in ["53th", "1th", "12nd", "111th", "22th", "avenue"]] == [
        "53rd", "1st", "12th", "111th", "22nd", "avenue"]

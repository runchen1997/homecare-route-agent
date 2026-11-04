"""Reading the patient list."""

import pytest

from homecare.patients import minutes, read_patients


def write(tmp_path, text):
    path = tmp_path / "patients.csv"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_each_row_becomes_a_patient_with_an_id():
    patients = read_patients("examples/patients.csv")
    assert len(patients) == 8
    first, second = patients[0], patients[1]
    assert (first.id, first.name, first.address) == ("P1", "Elena Russo", "6302 18th Ave, Brooklyn")
    assert (first.earliest, first.latest) == (None, None)
    assert (second.id, second.latest) == ("P2", 12 * 60)


@pytest.mark.parametrize(("text", "value"), [("13:00", 780), ("9:30", 570), ("", None), (" 08:05 ", 485)])
def test_times_are_minutes_after_midnight(text, value):
    assert minutes(text) == value


@pytest.mark.parametrize("text", ["1pm", "25:00", "12:60", "noon"])
def test_a_time_not_written_as_hh_mm_is_refused(text):
    with pytest.raises(ValueError, match="HH:MM"):
        minutes(text)


def test_a_mistake_names_the_row_to_fix(tmp_path):
    path = write(tmp_path, "name,address,earliest,latest\nAna,1 A St,,\nBo,2 B St,3pm,\n")
    with pytest.raises(ValueError, match=r"row 2 \(Bo\)"):
        read_patients(path)


def test_a_missing_column_or_address_is_refused(tmp_path):
    with pytest.raises(ValueError, match="no column latest"):
        read_patients(write(tmp_path, "name,address,earliest\nAna,1 A St,\n"))
    with pytest.raises(ValueError, match="needs a name and an address"):
        read_patients(write(tmp_path, "name,address,earliest,latest\nAna,,,\n"))


def test_earliest_must_come_before_latest(tmp_path):
    with pytest.raises(ValueError, match="earliest must come before latest"):
        read_patients(write(tmp_path, "name,address,earliest,latest\nAna,1 A St,14:00,12:00\n"))

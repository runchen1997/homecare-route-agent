"""Reading the patient list, with a scripted stand-in for the language model."""

import pytest

from homecare import llm
from homecare.patients import EXAMPLES, Patient, minutes, read_patient, read_patients, rows


def scripted(*answers):
    """A stand-in for llm.ask that gives `answers` in turn and keeps what it was asked."""
    replies, asked = iter(answers), []

    def ask(messages, schema, max_tokens):
        asked.append(list(messages))
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    ask.asked = asked
    return ask


def answer(name="Ana", address="1 A St", earliest="", latest=""):
    return {"name": name, "address": address, "earliest": earliest, "latest": latest}


def test_each_row_is_given_to_the_model_as_column_value_lines():
    texts = rows("examples/patients.csv")
    assert len(texts) == 8
    assert texts[1] == "name: Victor Huang\naddress: 1703 65th St, Brooklyn\nearliest: \nlatest: 12:00"


def test_the_model_sees_the_examples_then_the_row():
    ask = scripted(answer(latest="12:00"))
    patient = read_patient("name: Ana\naddress: 1 A St\nlatest: noon", "P1", ask)
    assert patient == Patient("P1", "Ana", "1 A St", None, 12 * 60)
    messages = ask.asked[0]
    assert messages[0]["role"] == "system"
    assert len(messages) == 2 + 2 * len(EXAMPLES)  # system, the examples' rows and answers, the row
    assert messages[-1]["content"] == "name: Ana\naddress: 1 A St\nlatest: noon"


def test_a_mistake_goes_back_to_the_model_for_another_try():
    ask = scripted(answer(earliest="1pm"), answer(earliest="13:00"))
    assert read_patient("Ana, 1 A St, after 1pm", "P1", ask).earliest == 13 * 60
    assert "'1pm' is not a time" in ask.asked[1][-1]["content"]


def test_a_row_the_model_cant_read_is_reported():
    ask = scripted(*[answer(earliest="14:00", latest="12:00")] * 3)
    with pytest.raises(ValueError, match="couldn't read P4's row"):
        read_patient("Ana, 1 A St", "P4", ask)


def test_an_answer_cut_off_is_asked_again():
    ask = scripted(llm.CutOff("cut off"), answer())
    assert read_patient("Ana, 1 A St", "P1", ask).name == "Ana"


def test_every_row_is_read_in_order(tmp_path):
    path = tmp_path / "patients.csv"
    path.write_text("Patient,Where\nAna,1 A St\nBo,2 B St\n", encoding="utf-8")
    ask = scripted(answer("Ana", "1 A St"), answer("Bo", "2 B St"))
    assert [(p.id, p.name) for p in read_patients(str(path), ask)] == [("P1", "Ana"), ("P2", "Bo")]


def test_a_list_with_no_patients_is_refused(tmp_path):
    path = tmp_path / "patients.csv"
    path.write_text("name,address\n", encoding="utf-8")
    with pytest.raises(ValueError, match="has no patients"):
        rows(str(path))


@pytest.mark.parametrize(("text", "value"), [("13:00", 780), ("9:30", 570), ("", None), (" 08:05 ", 485)])
def test_times_are_minutes_after_midnight(text, value):
    assert minutes(text) == value


@pytest.mark.parametrize("text", ["1pm", "25:00", "12:60", "noon"])
def test_a_time_not_written_as_hh_mm_is_refused(text):
    with pytest.raises(ValueError, match="HH:MM"):
        minutes(text)

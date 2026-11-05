"""The agent loop, with a scripted stand-in for the language model."""

import pytest

from homecare import agent, llm
from homecare.addresses import AddressError, Place
from homecare.agent import Agent, Request, numbered

CSV = "Patient,Where\nAna,1 A St\nBo,2 B St\n"


def scripted(*answers):
    """A stand-in for llm.ask that gives `answers` in turn and keeps what it was asked."""
    replies, asked = iter(answers), []

    def ask(messages, schema, max_tokens):
        asked.append((list(messages), schema))
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    ask.asked = asked
    return ask


def submit(order, thinking="done"):
    return {"thinking": thinking, "action": "submit_plan", "places": [], "order": order}


def look_up(**places):
    return {"thinking": "where are they?", "action": "find_address", "order": [],
            "places": [{"place": place, "address": address} for place, address in places.items()]}


def find(address):
    """A stand-in for addresses.find that knows two addresses."""
    known = {"1 A St": Place("1 A Street, Brooklyn 11201", 40.1, -73.1),
             "9 Home St": Place("9 Home Street, Brooklyn 11209", 40.9, -73.9)}
    if address not in known:
        raise AddressError(f'not found: no street called "{address}"')
    return known[address]


def make(*answers):
    ask = scripted(*answers)
    return Agent(Request(CSV, "9 Home St"), ask, log=lambda *_: None, find=find), ask


def test_the_list_gets_an_id_column():
    text, ids = numbered("name,address\nAna,\"1 A St, Brooklyn\"\n\nBo,2 B St\n")
    assert ids == ["P1", "P2"]  # the empty line is skipped
    assert text == "id,name,address\nP1,Ana,\"1 A St, Brooklyn\"\nP2,Bo,2 B St\n"


def test_a_list_with_no_patients_is_refused():
    with pytest.raises(ValueError, match="at least one patient"):
        numbered("name,address\n")


def test_the_model_sees_the_task_and_the_list_then_submits():
    a, ask = make(submit(["P2", "P1"]))
    result = a.run()
    assert (result.order, result.ended, len(result.steps)) == (["P2", "P1"], "submitted", 1)
    messages, schema = ask.asked[0]
    assert "submit_plan: hand in your plan" in messages[0]["content"]
    assert "Home: 9 Home St" in messages[1]["content"]
    assert "id,Patient,Where\nP1,Ana,1 A St\nP2,Bo,2 B St" in messages[1]["content"]


def test_each_step_must_name_a_real_action_and_real_patients():
    schema = make()[0].schema()
    assert schema["properties"]["action"]["enum"] == ["find_address", "submit_plan"]
    assert schema["properties"]["order"]["items"]["enum"] == ["P1", "P2"]
    assert schema["properties"]["places"]["items"]["properties"]["place"]["enum"] == ["P1", "P2", "home"]
    assert schema["required"] == ["thinking", "action", "places", "order"]


def test_the_model_looks_up_addresses_and_sees_what_was_found():
    a, ask = make(look_up(P1="1 A St", P2="2 B St", home="9 Home St"), submit(["P1"]))
    result = a.run()
    assert result.steps[0].result == ('P1: found 1 A Street, Brooklyn 11201\n'
                                      'P2: not found: no street called "2 B St"\n'
                                      'home: found 9 Home Street, Brooklyn 11209')
    assert ask.asked[1][0][-1]["content"].startswith("Result of find_address: P1: found")
    assert sorted(a.found) == ["P1", "home"]  # kept for working out travel times later


def test_an_answer_cut_off_uses_up_a_step():
    a, ask = make(llm.CutOff("cut off"), submit(["P1"]))
    assert a.run().order == ["P1"]
    assert "cut off" in ask.asked[1][0][-1]["content"]


def test_a_model_that_never_finishes_is_stopped(monkeypatch):
    monkeypatch.setattr(agent, "MAX_STEPS", 3)
    a, _ = make(*[llm.CutOff("cut off")] * 3)
    result = a.run()
    assert (result.order, result.ended) == ([], "step limit")

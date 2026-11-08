"""The model's judgement of how many extra minutes walking less is worth (a stand-in for the model)."""

from homecare.judging import put_up_with


def asking(value):
    asked = []

    def ask(messages, schema, max_tokens):
        asked.append(messages[0]["content"])
        return {"most_extra_minutes_worth_it": value}
    ask.asked = asked
    return ask


def test_the_model_is_asked_for_minutes_worth_the_walking_saved():
    ask = asking(4)
    assert put_up_with(28, 2.3, 0.4, ask=ask) == 4
    assert ask.asked == ["A home-care nurse carries an equipment bag. Walking all the way takes 28 min (2.3 km). How "
                         "many extra minutes would the nurse put up with, at most, to walk 0.4 km less? Answer in JSON."]


def test_when_the_quickest_way_rides_its_walking_is_said_so():
    ask = asking(6)
    put_up_with(18, 1.5, 1.0, all_the_way=False, ask=ask)
    assert "Walking on the quickest way takes 18 min (1.5 km)." in ask.asked[0]


def test_a_value_below_nothing_is_nothing():
    assert put_up_with(10, 0.8, 0.2, ask=asking(-3)) == 0

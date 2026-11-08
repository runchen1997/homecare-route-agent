"""The model's judgement where time and walking pull apart: how much walking saved is worth.

A way to go by bus can be a minute slower than walking and still be the one to take, for a nurse
carrying an equipment bag; or many minutes slower for a few steps saved, and not worth it. The
model judges this, but is asked only for a value: how many extra minutes, at most, the nurse would
put up with to walk so much less. Code compares that with the bus's real extra minutes.

Asked to choose between the ways themselves (A or B, or "should the nurse take the bus?"), the
same model took the bus every time, even 18 minutes slower to save 0.1 km, or walked every time,
or chose by where a way was in the list; asked for this value, it was right in 40 of 40 clear
cases (with either wording below). Other wordings of the value question did worse (19-20 of 24):
they overvalued saving a little of a short walk.
"""

from homecare import llm

ANSWER = {"type": "object", "properties": {"most_extra_minutes_worth_it": {"type": "integer"}},
          "required": ["most_extra_minutes_worth_it"]}


def put_up_with(walk_minutes: float, walk_km: float, fewer_km: float, all_the_way: bool = True, ask=llm.ask) -> int:
    """How many extra minutes, at most, the nurse would put up with to walk `fewer_km` less than the
    quickest way, which walks `walk_km` (`walk_minutes`): all the way, or to and from a train or bus."""
    if all_the_way:
        quickest = f"Walking all the way takes {round(walk_minutes)} min ({walk_km:.1f} km)."
    else:
        # Worded like the one above: "The quickest way to go has X min of walking" overvalued saving a little
        # of a short walk (38 of 40 clear cases); this was right in 40 of 40.
        quickest = f"Walking on the quickest way takes {round(walk_minutes)} min ({walk_km:.1f} km)."
    answer = ask([{"role": "user", "content": f"A home-care nurse carries an equipment bag. {quickest} How many extra "
                                              f"minutes would the nurse put up with, at most, to walk {fewer_km:.1f} km "
                                              f"less? Answer in JSON."}], ANSWER, 100)
    return max(int(answer["most_extra_minutes_worth_it"]), 0)

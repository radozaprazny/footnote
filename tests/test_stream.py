import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sse_client import WALL_START_MS, FakeClock, collect, parse
from strategies import events

from matchlens.events import MAX_PERIOD_MS, Event, EventType, make_event_id
from matchlens.generator import generate_match
from matchlens.stream import (
    HEARTBEAT_S,
    RETRY_MS,
    YIELD_EVERY,
    end_id,
    replay,
    replay_offsets,
    resume_index,
    sse,
)


@pytest.fixture(scope="module")
def match():
    return generate_match(7)


# --- timeline ------------------------------------------------------------------------------------


@st.composite
def timelines(draw) -> list[Event]:
    """Period-end markers at sorted (period, clock) instants: the cheapest valid events."""
    instants = sorted(
        draw(
            st.lists(st.tuples(st.sampled_from((1, 2)), st.integers(0, MAX_PERIOD_MS)), min_size=1)
        )
    )
    return [
        Event(make_event_id("m1", i), period, clock, EventType.PERIOD_END)
        for i, (period, clock) in enumerate(instants)
    ]


@given(timelines())
def test_offsets_are_one_continuous_timeline(events_):
    offsets = replay_offsets(events_)
    assert offsets == sorted(offsets)
    first_half = [o for o, e in zip(offsets, events_, strict=True) if e.period == 1]
    second_half = [o for o, e in zip(offsets, events_, strict=True) if e.period == 2]
    if first_half and second_half:
        assert min(second_half) >= max(first_half)
    end_of_first = max((e.clock_ms for e in events_ if e.period == 1), default=0)
    for o, e in zip(offsets, events_, strict=True):
        # period 1 is not shifted, period 2 starts right where period 1 ended: no break
        assert o - e.clock_ms == (0 if e.period == 1 else end_of_first)


def test_second_half_starts_where_the_first_ended(match):
    offsets = replay_offsets(match.events)
    end_of_first = next(e for e in match.events if e.type is EventType.PERIOD_END)
    kick_off = next(i for i, e in enumerate(match.events) if e.period == 2)
    assert offsets[kick_off] == end_of_first.clock_ms + match.events[kick_off].clock_ms


# --- resume --------------------------------------------------------------------------------------


@given(st.data())
@settings(max_examples=30)
def test_resume_starts_after_the_last_seen_event(match, data):
    k = data.draw(st.integers(0, len(match.events) - 1))
    assert resume_index(match.events, match.events[k].event_id) == k + 1


@pytest.mark.parametrize("empty", [None, ""])
def test_no_last_event_id_starts_at_the_beginning(match, empty):
    assert resume_index(match.events, empty) == 0


@pytest.mark.parametrize(
    ("last", "message"),
    [
        ("m8-e00001", "is not an event of this match"),
        ("m7-e99999", "is not an event of this match"),
        ("garbage", "is not an event id"),
        ("m7-e1", "is not an event id"),
    ],
)
def test_foreign_or_malformed_last_event_id_is_refused(match, last, message):
    with pytest.raises(ValueError, match=message):
        resume_index(match.events, last)


# --- message format ------------------------------------------------------------------------------


@given(events())
def test_sse_message_round_trips_an_event(event):
    text = sse("match_event", {"event": event.to_dict()}, event_id=event.event_id)
    assert text.endswith("\n\n") and text.count("\n\n") == 1
    (message,) = parse(text)
    assert message["id"] == event.event_id
    assert message["event"] == "match_event"
    assert Event.from_dict(message["data"]["event"]) == event


def test_retry_comes_first_when_given():
    assert sse("meta", {}, retry_ms=2000).startswith("retry: 2000\nevent: meta\n")


@given(
    st.dictionaries(
        st.text(), st.text() | st.integers() | st.floats(allow_nan=False, allow_infinity=False)
    )
)
def test_any_payload_stays_one_message_with_one_data_line(data):
    text = sse("narrative", data, event_id="m7-e00001")
    assert text.count("\n\n") == 1 and text.endswith("\n\n")
    (message,) = parse(text)
    assert message["data"] == data


@pytest.mark.parametrize(
    ("kind", "event_id", "data", "message"),
    [
        ("a\nb", None, {}, "contains a line break or NUL"),
        ("ok", "m7-e00001\r", {}, "contains a line break or NUL"),
        ("ok", "m7\0", {}, "contains a line break or NUL"),
        ("ok", None, {"x": float("nan")}, "Out of range float"),
        ("ok", None, {"x": float("inf")}, "Out of range float"),
    ],
)
def test_framing_breakers_are_refused(kind, event_id, data, message):
    with pytest.raises(ValueError, match=message):
        sse(kind, data, event_id=event_id)


# --- replay --------------------------------------------------------------------------------------


@pytest.mark.parametrize("speed", [0.5, 1.0, 10.0, 250.0])
def test_events_are_emitted_on_schedule_with_their_timestamp(match, speed):
    fake = FakeClock()
    messages = parse("".join(collect(replay(match, speed, clock=fake.clock()))))
    offsets = replay_offsets(match.events)
    sent = [m for m in messages if m.get("event") == "match_event"]
    assert [m["id"] for m in sent] == [e.event_id for e in match.events]
    for m, offset in zip(sent, offsets, strict=True):
        due_ms = (offset - offsets[0]) / speed
        assert abs((m["data"]["emitted_at_ms"] - WALL_START_MS) - due_ms) <= 1
        assert m["data"]["replay_ms"] == offset
    assert max(fake.sleeps) <= HEARTBEAT_S
    assert fake.t == pytest.approx((offsets[-1] - offsets[0]) / 1000 / speed)


def test_every_message_carries_an_emit_timestamp_and_heartbeats_fill_long_gaps(match):
    fake = FakeClock()
    messages = parse("".join(collect(replay(match, 1.0, clock=fake.clock()))))
    assert messages[0]["event"] == "meta" and messages[0]["retry"] == str(RETRY_MS)
    assert messages[0]["data"]["meta"] == match.meta.to_dict()
    assert messages[-1]["event"] == "end"
    for m in messages:
        if "comment" in m:
            assert m["comment"].startswith("heartbeat ")
        else:
            assert isinstance(m["data"]["emitted_at_ms"], int)
    assert messages[-1]["id"] == end_id(match.meta.match_id)


def test_the_wire_is_never_silent_longer_than_the_heartbeat(match):
    """Every 15 s gap gets its heartbeats, not just the first one of a long gap."""
    fake = FakeClock()
    messages = parse("".join(collect(replay(match, 1.0, clock=fake.clock()))))
    on_wire = [
        int(m["comment"].removeprefix("heartbeat "))
        if "comment" in m
        else m["data"]["emitted_at_ms"]
        for m in messages
    ]
    assert on_wire == sorted(on_wire)
    assert max(b - a for a, b in zip(on_wire, on_wire[1:], strict=False)) <= HEARTBEAT_S * 1000 + 1
    offsets = replay_offsets(match.events)
    gaps = [b - a for a, b in zip(offsets, offsets[1:], strict=False)]
    expected = sum(math.ceil(g / (HEARTBEAT_S * 1000)) - 1 for g in gaps if g > 0)
    assert expected > 0 and sum("comment" in m for m in messages) == expected


def test_speed_zero_never_waits_but_lets_other_streams_run(match, monkeypatch):
    turns = []

    async def count_turn(seconds):
        turns.append(seconds)

    monkeypatch.setattr("matchlens.stream.asyncio_sleep", count_turn)
    fake = FakeClock()
    messages = parse("".join(collect(replay(match, 0, clock=fake.clock()))))
    assert fake.sleeps == []
    assert turns == [0] * ((len(match.events) - 1) // YIELD_EVERY)
    assert len(messages) == len(match.events) + 2


@given(st.data())
@settings(max_examples=10, deadline=None)
def test_resumed_replay_sends_the_rest_from_its_own_start(match, data):
    k = data.draw(st.integers(0, len(match.events)))
    fake = FakeClock()
    messages = parse("".join(collect(replay(match, 2.0, start=k, clock=fake.clock()))))
    sent = [m for m in messages if m.get("event") == "match_event"]
    assert [m["id"] for m in sent] == [e.event_id for e in match.events[k:]]
    if sent:
        assert sent[0]["data"]["emitted_at_ms"] == WALL_START_MS  # no wait for the first one
    assert messages[-1]["event"] == "end"

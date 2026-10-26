"""The live stream: events, tracking frames and overlay cues merged on one timeline."""

import asyncio
import dataclasses
import gc
import itertools
import logging
import threading
import time
from collections import Counter

import httpx
import pytest
import real
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sse_client import WALL_START_MS, FakeClock, collect, parse
from strategies import event_streams

from matchlens.api import _DaemonWorker, create_app
from matchlens.events import FRAME_MS, PERIODS, EventType, make_frame_id
from matchlens.match import Match
from matchlens.render.cues import Cue, CueKind, CueRendition
from matchlens.render.moments import Overlay
from matchlens.stream import (
    DEFAULT_HZ,
    LIVE_HZ,
    RANK,
    Kind,
    end_id,
    live,
    live_timeline,
    tracking_ends,
)

# --- the timeline, on random event streams and cues ---------------------------------------------


def cue(match_id: str, n: int, due: tuple[int, int], event_ids=()) -> Cue:
    return Cue(
        f"{match_id}/cue/window/{n}", match_id, due, CueKind.WINDOW, ("x",), (), (), event_ids
    )


def fan_cites(c: Cue, event_ids) -> Cue:
    """`c` with a fan rendition that cites `event_ids`."""
    return dataclasses.replace(c, renditions=(CueRendition("fan", ("y",), (), event_ids),))


def slovak_cites(c: Cue, event_ids) -> Cue:
    """`c` with the analyst's lines in Slovak, which cite `event_ids`."""
    sk = CueRendition("analyst", ("z",), (), event_ids, "sk")
    return dataclasses.replace(c, translations=(sk,))


@st.composite
def streams(draw):
    """Events, cues that cite some of them (due at or after the last cited one, or citing none),
    some with a fan rendition or a translation that cites others of them, and the tracking ends
    of both periods, as `live_timeline` takes them."""
    _, events = draw(event_streams())
    match_id = events[0].event_id.split("-")[0]
    cues = []
    for n in range(draw(st.integers(0, 8))):
        anchor = events[draw(st.integers(0, len(events) - 1))]
        cited = draw(st.lists(st.sampled_from(events[: events.index(anchor) + 1]), max_size=3))
        late = draw(st.sampled_from([0, 1, draw(st.integers(0, 30_000))]))
        c = cue(match_id, n, (anchor.period, anchor.clock_ms + late), cited_ids(cited))
        if draw(st.booleans()):
            fan = draw(st.lists(st.sampled_from(events[: events.index(anchor) + 1]), max_size=3))
            c = fan_cites(c, cited_ids(fan))
        if draw(st.booleans()):
            sk = draw(st.lists(st.sampled_from(events[: events.index(anchor) + 1]), max_size=3))
            c = slovak_cites(c, cited_ids(sk))
        cues.append(c)
    ends = {
        e.period: e.clock_ms + draw(st.sampled_from([0, 1, 99, 100]))
        for e in events
        if e.type is EventType.PERIOD_END
    }
    return match_id, events, cues, ends


def cited_ids(events) -> tuple[str, ...]:
    return tuple(dict.fromkeys(e.event_id for e in events))


@given(streams(), st.sampled_from(LIVE_HZ))
def test_timeline_is_every_message_once_in_match_time_order(stream, hz):
    match_id, events, cues, ends = stream
    tl = live_timeline(match_id, events, cues, ends, hz)
    items = tl.items
    assert tl.first_half_ms == max(e.clock_ms for e in events if e.period == 1)
    keys = [(i.period, i.clock_ms, RANK[i.kind]) for i in items]
    assert keys == sorted(keys)
    assert all((i.period, i.clock_ms) == i.obj.due for i in items if i.kind == Kind.CUE)
    assert [i.obj for i in items if i.kind == Kind.EVENT] == events
    assert [i.obj for i in items if i.kind == Kind.CUE] == sorted(cues, key=lambda c: c.due)
    assert len({i.id for i in items}) == len(items)


@given(streams(), st.sampled_from(LIVE_HZ))
def test_a_cue_never_precedes_an_event_it_cites(stream, hz):
    match_id, events, cues, ends = stream
    position = {
        i.id: n for n, i in enumerate(live_timeline(match_id, events, cues, ends, hz).items)
    }
    for c in cues:
        texts = (*c.renditions, *c.translations)
        cited = [*c.event_ids, *(e for r in texts for e in r.event_ids)]
        assert all(position[e] < position[c.cue_id] for e in cited)


@given(streams(), st.sampled_from(LIVE_HZ))
def test_frame_count_matches_hz(stream, hz):
    match_id, events, cues, ends = stream
    frames = [
        i for i in live_timeline(match_id, events, cues, ends, hz).items if i.kind == Kind.FRAME
    ]
    step = 1000 // hz
    for period, end in ends.items():
        clocks = [f.clock_ms for f in frames if f.period == period]
        assert clocks == list(range(0, end + 1, step))
        assert len(clocks) == end // step + 1
    assert [f.id for f in frames] == [make_frame_id(match_id, f.period, f.clock_ms) for f in frames]


def test_frame_count_on_both_sides_of_a_step():
    events = real.match(7).events
    for end, count in [(999, 1), (1000, 2), (1001, 2), (1999, 2), (2000, 3)]:
        items = live_timeline("m7", events, [], {1: end}, 1).items
        assert sum(i.kind == Kind.FRAME for i in items) == count


@given(streams())
def test_a_cue_due_exactly_at_its_event_comes_after_it_and_one_ms_before_is_refused(stream):
    match_id, events, _, ends = stream
    e = events[-1]
    on_time = cue(match_id, 0, (e.period, e.clock_ms), (e.event_id,))
    items = live_timeline(match_id, events, [on_time], ends).items
    assert [i.id for i in items].index(on_time.cue_id) > [i.id for i in items].index(e.event_id)
    early = cue(match_id, 0, (e.period, e.clock_ms - 1), (e.event_id,))
    with pytest.raises(ValueError, match="due before"):
        live_timeline(match_id, events, [early], ends)
    live_timeline(match_id, events, [fan_cites(on_time, (e.event_id,))], ends)
    with pytest.raises(ValueError, match="due before"):  # a rendition's event, too
        live_timeline(
            match_id, events, [fan_cites(cue(match_id, 0, early.due), (e.event_id,))], ends
        )
    live_timeline(match_id, events, [slovak_cites(on_time, (e.event_id,))], ends)
    with pytest.raises(ValueError, match="due before"):  # and a translation's
        live_timeline(
            match_id, events, [slovak_cites(cue(match_id, 0, early.due), (e.event_id,))], ends
        )
    if e.period == 2:
        previous_period = cue(match_id, 0, (1, 10**9), (e.event_id,))
        with pytest.raises(ValueError, match="due before"):
            live_timeline(match_id, events, [previous_period], ends)


def test_a_cue_citing_an_unknown_event_and_a_bad_hz_are_refused():
    events = real.match(7).events
    with pytest.raises(ValueError, match="not in the stream"):
        live_timeline("m7", events, [cue("m7", 0, (2, 0), ("m7-e99999",))], {1: 0})
    with pytest.raises(ValueError, match="not in the stream"):
        live_timeline("m7", events, [fan_cites(cue("m7", 0, (2, 0)), ("m7-e99999",))], {1: 0})
    for hz in (0, 3, 4, 20, -5):
        with pytest.raises(ValueError, match="hz"):
            live_timeline("m7", events, [], {1: 0}, hz)


# --- Match.frames at a lower rate and from a start -----------------------------------------------


@pytest.fixture(scope="module")
def all_frames():
    return list(real.match(7).frames())


@settings(max_examples=40, deadline=None)
@given(
    st.sampled_from([100, 200, 500, 1000, 3000]),
    st.sampled_from(PERIODS),
    st.integers(0, 2_910_000),
)
def test_frames_every_and_from_start_are_the_full_tracking_filtered(
    all_frames, every, period, clock
):
    m = real.match(7)
    expected = [
        f
        for f in all_frames
        if (f.period, f.clock_ms) >= (period, clock) and f.clock_ms % every == 0
    ][:20]
    assert list(itertools.islice(m.frames(every, (period, clock)), 20)) == expected


def test_frames_start_on_and_one_ms_after_a_frame(all_frames):
    m = real.match(7)
    assert next(m.frames(200, (1, 400))).clock_ms == 400
    assert next(m.frames(200, (1, 401))).clock_ms == 600
    last = all_frames[-1]
    assert list(m.frames(100, (2, last.clock_ms))) == [last]
    assert list(m.frames(100, (2, last.clock_ms + 1))) == []


@pytest.mark.parametrize("every", [0, -100, 50, 150])
def test_frames_refuse_a_step_that_is_not_a_multiple_of_the_tracking(every):
    with pytest.raises(ValueError, match="multiple"):
        next(real.match(7).frames(every))


# --- the stream of a real match ---------------------------------------------------------------


@pytest.fixture(scope="module")
def match() -> Match:
    return real.match(7)


@pytest.fixture(scope="module")
def cues():
    return real.cues(7)


def timeline(match, cues, hz=DEFAULT_HZ):
    return live_timeline(match.meta.match_id, match.events, cues, tracking_ends(match), hz)


def messages(match, tl, speed=0.0, start=0, fake=None):
    return parse("".join(collect(live(match, tl, speed, start, (fake or FakeClock()).clock()))))


def test_full_stream_at_one_hz(match, cues):
    tl = timeline(match, cues, 1)
    got = messages(match, tl)
    assert [m["event"] for m in got[:1] + got[-1:]] == ["meta", "end"]
    assert got[0]["data"]["hz"] == 1 and got[0]["retry"] == "1000"
    assert got[0]["data"]["first_half_ms"] == tl.first_half_ms
    assert got[-1]["id"] == end_id("m7")
    body = got[1:-1]
    assert [m["id"] for m in body] == [i.id for i in tl.items]
    assert [m["event"] for m in body] == [i.kind for i in tl.items]
    counts = Counter(m["event"] for m in body)
    assert counts["match_event"] == len(match.events) and counts["cue"] == len(cues)
    by_id = {c.cue_id: c for c in cues}
    for m in body:
        if m["event"] == "cue":
            assert m["data"]["cue"] == by_id[m["id"]].to_dict()
        elif m["event"] == "match_event":
            assert m["data"]["event"]["event_id"] == m["id"]
    frames = [m["data"] for m in body if m["event"] == "frame"]
    assert all(f["clock_ms"] % 1000 == 0 for f in frames)
    sample = frames[1234]
    exact = match.frame_at(sample["period"], sample["clock_ms"])
    assert sample["players"] == [[p.player, round(p.x, 2), round(p.y, 2)] for p in exact.players]
    assert sample["ball"] == [round(exact.ball.x, 2), round(exact.ball.y, 2)]


def test_resume_around_half_time_yields_exactly_the_rest(match, cues):
    for hz in LIVE_HZ:
        tl = timeline(match, cues, hz)
        kickoff = next(n for n, i in enumerate(tl.items) if i.period == 2)
        for k in range(kickoff - 4, kickoff + 2):  # last frames, period end and its cue, kick-off
            rest = messages_head(match, tl, tl.resume_index(tl.items[k].id), 6)
            assert [m["id"] for m in rest[1:]] == [i.id for i in tl.items[k + 1 : k + 6]]


def messages_head(match, tl, start, n):
    """The first `n` messages of a stream from `start`, without sending the rest."""

    async def head():
        stream = live(match, tl, 0, start, FakeClock().clock())
        chunks = [await anext(stream) for _ in range(n)]
        await stream.aclose()
        return chunks

    return parse("".join(asyncio.run(head())))


def test_cues_never_precede_their_events_in_the_real_stream(match, cues):
    seen: set[str] = set()
    for m in messages(match, timeline(match, cues, 1))[1:-1]:
        if m["event"] == "cue":
            assert set(m["data"]["cue"]["event_ids"]) <= seen
        seen.add(m["id"])


@pytest.fixture(scope="module")
def full_at_one_hz(match, cues):
    tl = timeline(match, cues, 1)
    return tl, [strip(m) for m in messages(match, tl)]


def strip(message: dict) -> dict:
    """A message without its sending time, which differs between two runs."""
    data = {k: v for k, v in message.get("data", {}).items() if k != "emitted_at_ms"}
    return {**message, "data": data}


@settings(max_examples=8, deadline=None)
@given(st.data())
def test_resume_after_any_id_yields_exactly_the_rest(match, full_at_one_hz, data):
    tl, full = full_at_one_hz
    k = data.draw(st.integers(0, len(tl.items) - 1))
    start = tl.resume_index(tl.items[k].id)
    resumed = [strip(m) for m in messages(match, tl, start=start)]
    assert resumed[0]["event"] == "meta"
    assert resumed[1:] == full[k + 2 :]


def test_resume_after_the_last_item_sends_only_meta_and_end(match, cues):
    tl = timeline(match, cues, 1)
    got = messages(match, tl, start=tl.resume_index(tl.items[-1].id))
    assert [m["event"] for m in got] == ["meta", "end"]


def test_messages_leave_on_schedule_and_period_two_follows_period_one(match, cues):
    fake = FakeClock()
    tl = timeline(match, cues, 1)
    got = [m for m in messages(match, tl, speed=20, fake=fake) if "id" in m][:-1]
    first = got[0]["data"]["replay_ms"]
    for m in got:
        planned = (m["data"]["replay_ms"] - first) / 20
        assert abs(m["data"]["emitted_at_ms"] - WALL_START_MS - planned) <= 1
    kickoff_2 = next(m for m in got if m["event"] == "frame" and m["data"]["period"] == 2)
    assert kickoff_2["data"]["replay_ms"] == max(e.clock_ms for e in match.events if e.period == 1)


# --- the endpoint -----------------------------------------------------------------------------


@pytest.fixture
def client(match, cues):
    return TestClient(create_app([match, real.match(8)], FakeClock().clock(), {"m7": cues}))


def test_endpoint_streams_at_five_hz_by_default(client, match, cues):
    items = timeline(match, cues, 5).items
    r = client.get(f"/matches/m7/live?speed=0&last_event_id={items[-3].id}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    got = parse(r.text)
    assert got[0]["data"]["hz"] == DEFAULT_HZ == 5
    assert [m.get("id") for m in got] == [None, items[-2].id, items[-1].id, end_id("m7")]


def test_endpoint_resumes_with_header_or_query_and_the_header_wins(client, match, cues):
    items = timeline(match, cues, 2).items
    after = {
        m["id"]
        for m in parse(
            client.get(f"/matches/m7/live?speed=0&hz=2&last_event_id={items[-3].id}").text
        )
        if "id" in m
    }
    assert after == {items[-2].id, items[-1].id, end_id("m7")}
    r = client.get(
        f"/matches/m7/live?speed=0&hz=2&last_event_id={items[0].id}",
        headers={"Last-Event-ID": items[-2].id},
    )
    assert [m.get("id") for m in parse(r.text)] == [None, items[-1].id, end_id("m7")]


@pytest.mark.parametrize(
    ("query", "status"),
    [
        ("hz=3", 422),
        ("hz=0", 422),
        ("hz=20", 422),
        ("hz=five", 422),
        ("speed=0.05", 422),
        ("speed=-1", 422),
        ("last_event_id=m7-e99999", 400),
        ("last_event_id=m8-e00001", 400),
    ],
)
def test_bad_parameters_are_refused(client, query, status):
    assert client.get(f"/matches/m7/live?speed=0&{query}").status_code == status


def test_unknown_match_and_reconnect_after_end(client):
    assert client.get("/matches/m99/live").status_code == 404
    r = client.get("/matches/m7/live", headers={"Last-Event-ID": end_id("m7")})
    assert r.status_code == 204


@pytest.mark.parametrize("hz", LIVE_HZ)
def test_every_rate_is_served(client, match, cues, hz):
    last = timeline(match, cues, hz).items[-1].id  # resume at the end: meta and end only
    got = parse(client.get(f"/matches/m7/live?speed=0&hz={hz}&last_event_id={last}").text)
    assert [m["event"] for m in got] == ["meta", "end"]
    assert got[0]["data"]["hz"] == hz


def test_cue_timeline_is_computed_once_per_match_and_shared(match, monkeypatch):
    calls = []

    def fake_timeline(m, handoffs):
        calls.append(m.meta.match_id)
        return Overlay([])

    monkeypatch.setattr("matchlens.api.match_overlay", fake_timeline)
    app = create_app([match], FakeClock().clock())
    client = TestClient(app)
    for hz in (5, 5, 1):
        last = timeline(match, [], hz).items[-1].id  # resume at the end: a short stream
        assert (
            client.get(f"/matches/m7/live?speed=0&hz={hz}&last_event_id={last}").status_code == 200
        )
    assert calls == ["m7"]


def test_server_start_computes_every_cue_timeline(match, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "matchlens.api.match_overlay", lambda m, h: calls.append(m.meta.match_id) or Overlay([])
    )
    with TestClient(create_app([match, real.match(8)], FakeClock().clock())) as client:
        for m in (real.match(8), match):
            last = timeline(m, [], 1).items[-1].id
            r = client.get(f"/matches/{m.meta.match_id}/live?speed=0&hz=1&last_event_id={last}")
            assert r.status_code == 200
    assert calls == ["m7", "m8"]


def test_events_endpoint_is_unchanged_next_to_live(client, match):
    got = parse(client.get("/matches/m7/events?speed=0").text)
    assert [m["id"] for m in got[1:-1]] == [e.event_id for e in match.events]
    assert {m["event"] for m in got} == {"meta", "match_event", "end"}
    assert "hz" not in got[0]["data"]


def test_frame_step_is_a_multiple_of_the_tracking():
    assert all((1000 // hz) % FRAME_MS == 0 and 1000 % hz == 0 for hz in LIVE_HZ)


def test_a_first_connect_starts_at_the_first_frame(client, match, cues):
    tl = timeline(match, cues, 1)
    assert tl.resume_index(None) == tl.resume_index("") == 0
    with client.stream("GET", "/matches/m7/live?speed=0&hz=1") as r:
        head = parse("".join(itertools.islice(r.iter_text(), 3)).rsplit("\n\n", 1)[0] + "\n\n")
    assert head[1]["id"] == tl.items[0].id == make_frame_id("m7", 1, 0)


def test_one_app_serves_each_rate_its_own_timeline(client, match, cues):
    for hz in (5, 1, 10, 5):
        last = timeline(match, cues, hz).items[-3].id
        got = parse(client.get(f"/matches/m7/live?speed=0&hz={hz}&last_event_id={last}").text)
        assert got[0]["data"]["hz"] == hz
        assert len(got) == 4


def test_a_failed_cue_timeline_is_computed_again_on_the_next_request(match, monkeypatch):
    calls = []

    def flaky(m, handoffs):
        calls.append(m.meta.match_id)
        if len(calls) == 1:
            raise RuntimeError("first attempt fails")
        return Overlay([])

    monkeypatch.setattr("matchlens.api.match_overlay", flaky)
    client = TestClient(create_app([match], FakeClock().clock()), raise_server_exceptions=False)
    last = timeline(match, [], 1).items[-1].id
    url = f"/matches/m7/live?speed=0&hz=1&last_event_id={last}"
    assert client.get(url).status_code == 500
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 200
    assert calls == ["m7", "m7"]


def test_a_client_leaving_while_its_cue_timeline_is_queued_does_not_break_the_match(monkeypatch):
    """The client's cancel reaches the queued computation; the next client computes it anew."""
    m7, m8 = real.match(7), real.match(8)
    gate = threading.Event()
    calls = []

    def slow(m, handoffs):
        calls.append(m.meta.match_id)
        if m.meta.match_id == "m7":
            gate.wait(10)
        return Overlay([])

    monkeypatch.setattr("matchlens.api.match_overlay", slow)
    app = create_app([m7, m8])
    url = {
        m.meta.match_id: f"/matches/{m.meta.match_id}/live?speed=0&hz=1&last_event_id="
        f"{timeline(m, [], 1).items[-1].id}"
        for m in (m7, m8)
    }

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            first = asyncio.create_task(c.get(url["m7"]))
            await asyncio.sleep(0.3)  # m7 holds the single worker
            second = asyncio.create_task(c.get(url["m8"]))
            await asyncio.sleep(0.3)  # m8 waits behind it
            second.cancel()
            await asyncio.sleep(0.1)
            gate.set()
            assert (await first).status_code == 200
            return (await c.get(url["m8"])).status_code

    assert asyncio.run(run()) == 200
    assert calls == ["m7", "m8"]


# --- readiness --------------------------------------------------------------------------------


def wait_for(check, seconds: float = 10.0):
    deadline = time.monotonic() + seconds
    while not (got := check()) and time.monotonic() < deadline:
        time.sleep(0.01)
    return got


def readiness(client) -> tuple[int, dict]:
    r = client.get("/readyz")
    return r.status_code, r.json()


def test_ready_only_once_every_cue_timeline_is_computed(match, monkeypatch):
    """Two matches warming, then one, then none: only the last is ready. Liveness answers
    throughout, and a ready app stays ready."""
    gates = {"m7": threading.Event(), "m8": threading.Event()}
    started = []

    def slow(m, handoffs):
        started.append(m.meta.match_id)
        assert gates[m.meta.match_id].wait(10)
        return Overlay([])

    monkeypatch.setattr("matchlens.api.match_overlay", slow)
    with TestClient(create_app([match, real.match(8)], FakeClock().clock())) as client:
        assert wait_for(lambda: started == ["m7"])
        assert readiness(client) == (503, {"status": "warming", "pending": ["m7", "m8"]})
        assert client.get("/healthz").json() == {"status": "ok"}
        gates["m7"].set()
        assert wait_for(lambda: started == ["m7", "m8"])  # m7's result is set before m8 starts
        assert readiness(client) == (503, {"status": "warming", "pending": ["m8"]})
        assert client.get("/healthz").json() == {"status": "ok"}
        gates["m8"].set()
        assert wait_for(lambda: readiness(client)[0] == 200)
        assert readiness(client) == (200, {"status": "ok"})
    assert started == ["m7", "m8"]


def test_given_cue_timelines_are_ready_at_once(match, monkeypatch):
    def unused(m, handoffs):
        raise AssertionError("a given cue timeline was computed")

    monkeypatch.setattr("matchlens.api.match_overlay", unused)
    with TestClient(create_app([match], FakeClock().clock(), cues={"m7": []})) as client:
        assert readiness(client) == (200, {"status": "ok"})


def test_the_probe_queues_a_failed_cue_timeline_again(match, monkeypatch, caplog):
    calls = []

    def flaky(m, handoffs):
        calls.append(m.meta.match_id)
        if len(calls) == 1:
            raise RuntimeError("first attempt fails")
        return Overlay([])

    monkeypatch.setattr("matchlens.api.match_overlay", flaky)
    with (
        caplog.at_level(logging.ERROR, logger="matchlens.api"),
        TestClient(create_app([match], FakeClock().clock())) as client,
    ):
        assert wait_for(lambda: readiness(client)[0] == 200)
        assert readiness(client) == (200, {"status": "ok"})
    assert calls == ["m7", "m7"]
    (record,) = caplog.records  # the probe's retry says why, with the traceback
    assert record.getMessage() == "cue timeline of m7 failed, computing it again"
    assert str(record.exc_info[1]) == "first attempt fails"


def test_the_probe_queues_a_cue_timeline_a_leaving_client_cancelled(monkeypatch):
    """A cancelled timeline is done but not computed: the probe counts it as warming and queues
    it again, else the app would never become ready (or would claim it too early)."""
    m7, m8 = real.match(7), real.match(8)
    gate = threading.Event()
    calls = []

    def slow(m, handoffs):
        calls.append(m.meta.match_id)
        if m.meta.match_id == "m7":
            gate.wait(10)
        return Overlay([])

    submitted = []
    submit = _DaemonWorker.submit
    monkeypatch.setattr("matchlens.api.match_overlay", slow)
    monkeypatch.setattr(
        _DaemonWorker, "submit", lambda w, *a: submitted.append(submit(w, *a)) or submitted[-1]
    )
    app = create_app([m7, m8])
    url = {
        m.meta.match_id: f"/matches/{m.meta.match_id}/live?speed=0&hz=1&last_event_id="
        f"{timeline(m, [], 1).items[-1].id}"
        for m in (m7, m8)
    }

    async def until(check):
        deadline = time.monotonic() + 10
        while not check():
            assert time.monotonic() < deadline
            await asyncio.sleep(0.01)

    async def run():
        transport = httpx.ASGITransport(app=app)  # no lifespan: the requests queue the timelines
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            first = asyncio.create_task(c.get(url["m7"]))
            await until(lambda: calls == ["m7"])  # m7 holds the single worker
            second = asyncio.create_task(c.get(url["m8"]))
            await until(lambda: len(submitted) == 2)  # m8 waits behind it
            second.cancel()
            await until(lambda: submitted[1].cancelled())  # the leaving client's cancel
            r = await c.get("/readyz")
            warming = r.status_code, r.json()
            gate.set()
            deadline = time.monotonic() + 10
            while (r := await c.get("/readyz")).status_code != 200:
                assert time.monotonic() < deadline, r.json()
                await asyncio.sleep(0.01)
            assert (await first).status_code == 200
            return warming

    assert asyncio.run(run()) == (503, {"status": "warming", "pending": ["m7", "m8"]})
    assert calls == ["m7", "m8"]  # the cancelled m8 never ran; the probe's m8 did


def test_the_worker_runs_jobs_in_order_and_its_shutdown_cancels_the_queued_ones():
    done = []
    worker = _DaemonWorker()
    jobs = [worker.submit(lambda n: done.append(n) or n, n) for n in range(20)]
    assert [j.result(timeout=10) for j in jobs] == done == list(range(20))
    gate = threading.Event()
    running = worker.submit(lambda x: gate.wait(10) and x, "first")
    queued = worker.submit(lambda x: x, "second")
    thread = worker._thread
    assert thread.name == "cues" and thread.daemon  # a daemon thread is not joined at exit
    assert wait_for(running.running)
    worker.shutdown()
    assert queued.cancelled()
    with pytest.raises(RuntimeError, match="after shutdown"):
        worker.submit(lambda: None)
    gate.set()
    assert running.result(timeout=10) == "first"  # the running job is not cancelled
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_a_worker_dropped_without_shutdown_ends_its_thread():
    """Apps built and dropped without their lifespan (most tests) leave no thread behind."""
    worker = _DaemonWorker()
    assert worker.submit(lambda: "done").result(timeout=10) == "done"
    thread = worker._thread
    del worker
    gc.collect()
    thread.join(timeout=10)
    assert not thread.is_alive()

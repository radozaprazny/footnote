import pytest
from fastapi.testclient import TestClient
from sse_client import WALL_START_MS, FakeClock, parse

from matchlens.api import create_app
from matchlens.generator import generate_match
from matchlens.stream import replay_offsets


@pytest.fixture(scope="module")
def match():
    return generate_match(7)


@pytest.fixture
def fake():
    return FakeClock()


@pytest.fixture
def client(match, fake):
    return TestClient(create_app([match, generate_match(8)], clock=fake.clock()))


def ids(response) -> list[str]:
    return [m["id"] for m in parse(response.text) if m.get("event") == "match_event"]


def test_health_and_match_list(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    listed = client.get("/matches").json()
    assert [m["match_id"] for m in listed] == ["m7", "m8"]
    assert set(listed[0]) == {"match_id", "home", "away"}


def test_the_public_docs_carry_the_product_name(client):
    """`/docs`, `/redoc` and `/openapi.json` are public: they say Footnote, the product's name
    (issue #9); the package and the command line stay `matchlens`."""
    assert client.get("/openapi.json").json()["info"]["title"] == "Footnote"
    assert "<title>Footnote" in client.get("/docs").text
    assert "<title>Footnote" in client.get("/redoc").text


def test_full_stream(client, match):
    r = client.get("/matches/m7/events?speed=0")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"
    messages = parse(r.text)
    assert [m["event"] for m in messages[:1] + messages[-1:]] == ["meta", "end"]
    assert ids(r) == [e.event_id for e in match.events]


def test_default_speed_is_real_time(client, match, fake):
    r = client.get("/matches/m7/events")
    offsets = replay_offsets(match.events)
    last = [m for m in parse(r.text) if m.get("event") == "match_event"][-1]
    assert last["data"]["emitted_at_ms"] - WALL_START_MS == offsets[-1] - offsets[0]
    assert fake.t == pytest.approx((offsets[-1] - offsets[0]) / 1000)


def test_speed_scales_the_waits(client, match, fake):
    client.get("/matches/m7/events?speed=10")
    offsets = replay_offsets(match.events)
    assert fake.t == pytest.approx((offsets[-1] - offsets[0]) / 1000 / 10)


def test_resume_with_the_header_browsers_send(client, match):
    k = 100
    r = client.get(
        "/matches/m7/events?speed=0", headers={"Last-Event-ID": match.events[k].event_id}
    )
    assert ids(r) == [e.event_id for e in match.events[k + 1 :]]


def test_resume_with_a_query_parameter_and_the_header_wins(client, match):
    r = client.get(f"/matches/m7/events?speed=0&last_event_id={match.events[5].event_id}")
    assert ids(r)[0] == match.events[6].event_id
    r = client.get(
        f"/matches/m7/events?speed=0&last_event_id={match.events[5].event_id}",
        headers={"Last-Event-ID": match.events[50].event_id},
    )
    assert ids(r)[0] == match.events[51].event_id


def test_resume_after_the_last_event_sends_only_meta_and_end(client, match):
    r = client.get(
        "/matches/m7/events?speed=0", headers={"Last-Event-ID": match.events[-1].event_id}
    )
    assert [m["event"] for m in parse(r.text)] == ["meta", "end"]


@pytest.mark.parametrize(
    ("query", "status"),
    [
        ("speed=-1", 422),
        ("speed=1001", 422),
        ("speed=1e-9", 422),
        ("speed=1e-320", 422),
        ("speed=0.09", 422),
        ("speed=nan", 422),
        ("speed=inf", 422),
        ("speed=fast", 422),
        ("last_event_id=m8-e00001", 400),
        ("last_event_id=m7-e99999", 400),
        ("last_event_id=garbage", 400),
    ],
)
def test_bad_parameters_are_refused(client, query, status):
    r = client.get(f"/matches/m7/events?{query}")
    assert r.status_code == status


def test_unknown_match_is_404(client):
    r = client.get("/matches/m99/events")
    assert r.status_code == 404
    assert r.json() == {"detail": "unknown match m99"}


@pytest.mark.parametrize("speed", ["0", "0.1", "1000"])
def test_boundary_speeds_are_accepted(client, match, speed):
    r = client.get(f"/matches/m7/events?speed={speed}&last_event_id={match.events[-4].event_id}")
    assert r.status_code == 200
    assert len(ids(r)) == 3


def test_reconnect_after_end_gets_204_so_the_browser_stops(client, match):
    r = client.get("/matches/m7/events?speed=0")
    end = parse(r.text)[-1]
    assert end["event"] == "end" and end["id"] == "m7-end"
    again = client.get("/matches/m7/events", headers={"Last-Event-ID": end["id"]})
    assert again.status_code == 204 and again.text == ""
    other = client.get("/matches/m8/events", headers={"Last-Event-ID": "m7-end"})
    assert other.status_code == 400


def test_real_clock_replays_the_tail_of_a_match(match):
    """The default Clock: the last 20 events at 1000x arrive in their real order and spacing."""
    client = TestClient(create_app([match]))
    r = client.get(f"/matches/m7/events?speed=1000&last_event_id={match.events[-21].event_id}")
    sent = [m for m in parse(r.text) if m.get("event") == "match_event"]
    assert [m["id"] for m in sent] == [e.event_id for e in match.events[-20:]]
    emitted = [m["data"]["emitted_at_ms"] for m in sent]
    planned = [(m["data"]["replay_ms"] - sent[0]["data"]["replay_ms"]) / 1000 for m in sent]
    assert emitted == sorted(emitted)
    for e, p in zip(emitted, planned, strict=True):
        assert e - emitted[0] >= p - 1  # never early; lateness is up to the machine's load


def test_duplicate_match_ids_are_refused(match):
    with pytest.raises(ValueError, match="duplicate match id m7"):
        create_app([match, match])

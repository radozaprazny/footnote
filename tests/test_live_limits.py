"""Issue #2: what `/live` serves to anonymous clients (`LiveLimits`), each limit pinned on its
bound and one unit past it, and `matchlens serve` applying them. An app built without limits
serves any speed (the rest of the suite relies on speed 0)."""

import contextlib
import itertools
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import real
import uvicorn
from fastapi.testclient import TestClient
from sse_client import FakeClock

from matchlens.api import MIN_SPEED, LiveLimits, create_app

LAST = real.match(7).events[-1].event_id  # resume after it: a few messages, a short body
LOWER = "lower speed or hz"


def test_the_public_limits():
    """The page's most is 60× at 5 Hz: 300 frames a second, exactly a stream's bound; the
    budget is 4 viewers at the page's 30× and 5 Hz."""
    assert LiveLimits() == LiveLimits(
        min_speed=1.0, max_fps=300.0, budget_fps=600.0, max_streams=30, retry_after_s=5
    )


@pytest.mark.parametrize(
    ("speed", "hz", "admitted"),
    [(1, 5, True), (0.99, 5, False), (60, 5, True), (60.2, 5, False), (30, 10, True),
     (30.1, 10, False), (300, 1, True), (301, 1, False), (0, 1, False)],
)  # fmt: skip
def test_admits_is_a_streams_own_bounds(speed, hz, admitted):
    """`admits`, which a check of the page's links imports, on each bound and one step past."""
    assert LiveLimits().admits(speed, hz) is admitted


@pytest.fixture(scope="module")
def apps():
    m = real.match(7)
    limited = create_app([m], FakeClock().clock(), cues={"m7": []}, limits=LiveLimits())
    free = create_app([m], FakeClock().clock(), cues={"m7": []})
    with TestClient(limited) as a, TestClient(free) as b:
        yield a, b


@pytest.mark.parametrize(
    ("speed", "hz", "allowed"),
    [
        (0, 1, False),  # the whole match at once
        (MIN_SPEED, 1, False),  # slower than the public minimum: a slot held for hours
        (0.99, 1, False),
        (1, 1, True),  # the slowest replay here
        (60, 5, True),  # the page's most: 300 frames a second, on the bound
        (60.2, 5, False),  # 301
        (300, 1, True),
        (301, 1, False),
        (30, 10, True),
        (30.1, 10, False),
    ],
)
def test_speed_times_hz_is_bounded_and_speed_zero_refused(apps, speed, hz, allowed):
    limited, free = apps
    url = f"/matches/m7/live?speed={speed}&hz={hz}&last_event_id={LAST}"
    r = limited.get(url)
    assert r.status_code == (200 if allowed else 422), r.text
    if not allowed:  # the reason, word for word: the page shows it
        slow, fast = "speed must be at least 1 here", f"at most 300 frames a second here: {LOWER}"
        assert r.json()["detail"] == (slow if speed < 1 else fast)
    assert free.get(url).status_code == 200  # the limits refuse it, nothing else


def test_events_and_probes_are_never_limited(apps):
    limited, _ = apps
    assert limited.get("/matches/m7/events?speed=0").status_code == 200
    assert limited.get("/healthz").status_code == 200


@contextlib.contextmanager
def served(limits: LiveLimits, cold: bool = False) -> Iterator[httpx.Client]:
    """A real server in a thread (open streams need one) with `limits`, and a client of it.
    `cold`: the overlay is computed after the start (about 5 s), so a stream awaits it."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    app = create_app([real.match(7)], **({} if cold else {"cues": {"m7": []}}), limits=limits)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=1))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.05)
    port = sock.getsockname()[1]
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(10)


SLOW = "/matches/m7/live?speed=1&hz=1"  # stays open for the length of the match


def started(response: httpx.Response) -> Iterator[str]:
    """Asserts the stream runs (its first message, `meta`, arrived) and returns its lines: hold
    them, as httpx closes the connection when a partly read iterator is dropped."""
    assert response.status_code == 200
    lines = response.iter_lines()
    assert "event: meta" in itertools.islice(lines, 6)  # retry, id, event, data, blank
    return lines


def admitted(client: httpx.Client, url: str) -> int:
    """The status of a new stream of `url`, waiting up to 10 s for a slot (a closed stream frees
    its slot once the server sees the disconnect)."""
    deadline = time.monotonic() + 10
    while True:
        with client.stream("GET", url) as r:
            if r.status_code != 503 or time.monotonic() > deadline:
                return r.status_code
        time.sleep(0.05)


def test_open_streams_are_capped_and_a_closed_one_frees_its_slot():
    with served(LiveLimits(max_streams=2)) as client, client.stream("GET", SLOW) as a:
        held = [started(a)]
        with client.stream("GET", SLOW) as b:
            held.append(started(b))  # 2 open: the bound
            with client.stream("GET", SLOW) as full:  # left at once: a mutant must not hang
                assert full.status_code == 503 and full.headers["retry-after"] == "5"
                full.read()
                assert full.json() == {"detail": "too many streams open here, try again shortly"}
            assert client.get("/healthz").status_code == 200
            with client.stream("GET", "/matches/m7/events") as events:  # never limited
                assert events.status_code == 200
        assert admitted(client, SLOW) == 200  # 1 open: one under the bound
        assert len(held) == 2


def test_a_refused_request_and_an_ended_stream_hold_no_slot():
    with served(LiveLimits(max_streams=1)) as client:
        assert client.get("/matches/m7/live?speed=0").status_code == 422
        ended = client.get(f"/matches/m7/live?speed=300&hz=1&last_event_id={LAST}")
        assert ended.status_code == 200 and "event: end" in ended.text
        assert admitted(client, f"/matches/m7/live?speed=300&hz=1&last_event_id={LAST}") == 200


def test_requests_at_once_take_no_more_slots_than_there_are():
    """The slot is taken with the check, before the app awaits anything: of 12 requests sent
    together to a cold replica of 3 slots, while its overlay is still being computed, exactly 3
    stream and 9 are refused (a slot taken after that await let all of them through)."""
    with served(LiveLimits(max_streams=3), cold=True) as client:
        base = str(client.base_url)
        n = 12
        start, hold = threading.Barrier(n), threading.Event()
        statuses: list[int] = []
        lock = threading.Lock()

        def one() -> None:
            with httpx.Client(base_url=base, timeout=30) as mine:
                start.wait()
                with mine.stream("GET", SLOW) as r:
                    with lock:
                        statuses.append(r.status_code)
                    hold.wait(30)

        threads = [threading.Thread(target=one) for _ in range(n)]
        for t in threads:
            t.start()
        deadline = time.monotonic() + 30  # the admitted answer once the overlay is ready
        while len(statuses) < n and time.monotonic() < deadline:
            time.sleep(0.02)
        hold.set()
        for t in threads:
            t.join(10)
        assert sorted(statuses) == [200] * 3 + [503] * 9


# Room for one 1× stream at 1 Hz, by each bound alone: the count of streams, then the budget of
# frames a second (1 frame a second); a request must give back both its slot and its share.
ONE_SLOT = [LiveLimits(max_streams=1), LiveLimits(budget_fps=1)]


@pytest.fixture(params=ONE_SLOT, ids=["streams", "budget"])
def one_slot(request):
    """An app with one slot: a request that gives it back leaves it for the next."""
    app = create_app([real.match(7)], FakeClock().clock(), cues={"m7": []}, limits=request.param)
    with TestClient(app) as client:
        yield client


def test_a_refused_resume_gives_its_slot_back(one_slot):
    for _ in range(3):  # an id the timeline does not have: 400, after the slot was taken
        assert (
            one_slot.get("/matches/m7/live?speed=1&hz=1&last_event_id=m7-nope").status_code == 400
        )
    assert one_slot.get(f"/matches/m7/live?speed=1&hz=1&last_event_id={LAST}").status_code == 200


def test_a_finished_resume_takes_no_slot(one_slot):
    for _ in range(3):  # after the end message: 204, before any slot is taken
        assert one_slot.get("/matches/m7/live?speed=1&hz=1&last_event_id=m7-end").status_code == 204
    assert one_slot.get(f"/matches/m7/live?speed=1&hz=1&last_event_id={LAST}").status_code == 200


@pytest.mark.parametrize("limits", ONE_SLOT, ids=["streams", "budget"])
def test_a_failed_timeline_gives_its_slot_back_and_answers_500(monkeypatch, limits):
    """While the overlay fails (a bug, not the client's): 500, never 400, and the slot comes
    back each time; once it is computed, the stream runs."""
    from matchlens import api

    real_overlay, broken = api.match_overlay, [True]

    def failing(*args, **kwargs):
        if broken[0]:
            raise ValueError("internal boom")
        return real_overlay(*args, **kwargs)

    monkeypatch.setattr(api, "match_overlay", failing)
    app = create_app([real.match(7)], FakeClock().clock(), limits=limits)
    with TestClient(app, raise_server_exceptions=False) as client:
        url = f"/matches/m7/live?speed=1&hz=1&last_event_id={LAST}"
        assert [client.get(url).status_code for _ in range(3)] == [500, 500, 500]
        broken[0] = False
        assert client.get(url).status_code == 200


def test_a_stream_that_fails_midway_gives_its_slot_back(monkeypatch):
    """A stream that raises after its first message (a bug, not the client's) still gives back
    its slot and its share: the replica is not left full until a restart."""
    from matchlens import api

    async def broken(*args, **kwargs):
        yield "retry: 1\n\n"
        raise RuntimeError("boom")

    monkeypatch.setattr(api, "live", broken)
    for limits in ONE_SLOT:
        app = create_app([real.match(7)], FakeClock().clock(), cues={"m7": []}, limits=limits)
        with TestClient(app, raise_server_exceptions=False) as client:
            url = f"/matches/m7/live?speed=1&hz=1&last_event_id={LAST}"
            assert [client.get(url).status_code for _ in range(3)] == [200] * 3, limits


def test_the_open_streams_share_a_budget_of_frames_a_second():
    """The frames a second of the open streams together stay within `budget_fps`: on it a
    stream is admitted, one frame a second past it refused; a closed stream gives its share
    back. 1× at 1 Hz is 1 frame a second."""
    with served(LiveLimits(budget_fps=3)) as client:
        with client.stream("GET", SLOW) as a:
            held = [started(a)]  # 1 of 3
            with client.stream("GET", "/matches/m7/live?speed=3&hz=1") as over:
                assert over.status_code == 503  # 1 + 3 > 3
            with client.stream("GET", "/matches/m7/live?speed=2&hz=1") as b:
                held.append(started(b))  # 1 + 2 = 3: on the budget
                with client.stream("GET", SLOW) as full:
                    assert full.status_code == 503  # 3 + 1 > 3
            assert admitted(client, "/matches/m7/live?speed=2&hz=1") == 200  # b's share back
        assert len(held) == 2

"""The compact tracking of generator v2 (M9 item 6): every 100 ms frame kept in whole centimetres,
read back by `Match.frames()`, `frame_at()` and `snapshots_at()`, and judged by `validate_match`
frame by frame: each player within his own top speed in every step, the ball within its own,
everyone on the pitch, and every event where the frames have it."""

import re
from array import array

import pytest
from hypothesis import given
from hypothesis import strategies as st

from matchlens.events import (
    FRAMES_PER_PERIOD,
    MAX_PERIOD_MS,
    Event,
    EventType,
    MatchMeta,
    Outcome,
    PlayerPosition,
    Point,
    make_frame_id,
)
from matchlens.facts import _arrivals
from matchlens.match import MOVE_TOLERANCE, Match, Snapshot, Tracking, validate_match
from matchlens.stats.passing import pass_ratings
from matchlens.stream import tracking_ends

LINEUP = {t: tuple(f"{t}-p{i:02d}" for i in range(1, 12)) for t in ("cor", "vel")}
META = MatchMeta("m1", "cor", "vel", LINEUP["cor"], LINEUP["vel"], 1)
PLAYERS = LINEUP["cor"] + LINEUP["vel"]


def standing() -> list[int]:
    """One frame: the ball on the centre spot, everyone on his own spot at x = 10 m, 3 m apart."""
    row = [5250, 3400]
    for i, _ in enumerate(PLAYERS):
        row += [1000, 400 + 300 * i]
    return row


def moving(who: int, dx: int, dy: int, frames: int = 2) -> list[list[int]]:
    """`frames` frames in which `who` (0 the ball, 1 the first player) moves (dx, dy) cm a step."""
    out = []
    for n in range(frames):
        row = standing()
        row[2 * who] += n * dx
        row[2 * who + 1] += n * dy
        out.append(row)
    return out


def kept(*periods: list[list[int]], players: tuple[str, ...] = PLAYERS) -> Tracking:
    return Tracking(
        players,
        tuple(array("h", [v for row in rows for v in row]).tobytes() for rows in periods),
    )


def match_of(tracking: Tracking, *events: Event, snapshots: tuple = ()) -> Match:
    """`events`, then the two period ends at each period's last frame."""
    ends = tracking.ends()
    n = len(events)
    return Match(
        META,
        (
            *events,
            Event(f"m1-e{n:05d}", 1, ends.get(1, 0), EventType.PERIOD_END),
            Event(f"m1-e{n + 1:05d}", 2, ends.get(2, 0), EventType.PERIOD_END),
        ),
        snapshots,
        tracking,
    )


def refused(m: Match, message: str, speeds: dict | None = None) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        validate_match(m, speeds)


# --- reading the frames back --------------------------------------------------------------------


def test_frames_are_the_kept_centimetres_with_the_usual_ids():
    second = standing()
    second[0:4] = [5300, 3399, 1001, 450]  # the ball and cor-p01 moved
    m = match_of(kept([standing(), second], [standing()]))
    frames = list(m.frames())
    assert [(f.frame_id, f.period, f.clock_ms) for f in frames] == [
        ("m1-f000000", 1, 0),
        ("m1-f000001", 1, 100),
        (f"m1-f{FRAMES_PER_PERIOD:06d}", 2, 0),
    ]
    assert (frames[1].ball.x, frames[1].ball.y) == (53.0, 33.99)
    first = frames[1].players[0]
    assert (first.player, first.x, first.y) == ("cor-p01", 10.01, 4.5)
    last = frames[0].players[-1]
    assert (last.player, last.x, last.y) == ("vel-p11", 10.0, 67.0)
    assert [m.frame_at(f.period, f.clock_ms) for f in frames] == frames
    assert list(m.frames(start=(1, 100))) == frames[1:]
    assert list(m.frames(start=(1, 50))) == frames[1:]  # the first frame from it on
    assert list(m.frames(start=(2, 0))) == frames[2:]
    assert list(m.frames(every_ms=200)) == [frames[0], frames[2]]
    assert m.tracking.ends() == {1: 100, 2: 0}
    assert tracking_ends(m) == {1: 100, 2: 0}  # what the live stream runs to


@pytest.mark.parametrize(
    ("period", "clock_ms"), [(1, 200), (1, -100), (1, 50), (1, 100.0), (2, 100), (3, 0), (0, 0)]
)
def test_there_is_no_frame_off_the_grid_or_after_the_last(period, clock_ms):
    m = match_of(kept(moving(1, 1, 0), [standing()]))
    m.frame_at(1, 100)  # the last frame of period 1 is there
    assert not m.tracking.holds(period, clock_ms)
    with pytest.raises(ValueError, match="no frame at period"):
        m.frame_at(period, clock_ms)


def test_snapshots_at_read_the_frames_in_time_order_and_skip_what_is_not_kept():
    m = match_of(kept(moving(1, 30, 40, frames=3), [standing()]))
    got = m.snapshots_at([(2, 0), (1, 200), (1, 300), (1, 50), (1, 200)])
    assert [(s.period, s.clock_ms) for s in got] == [(1, 200), (2, 0)]
    assert got[0].ball == (52.5, 34.0)
    assert got[0].players[0] == ("cor-p01", 10.6, 4.8)
    assert got[1] == m.tracking.snapshot(2, 0)


def test_a_v1_match_gives_its_own_snapshots_at_those_instants():
    players = tuple((p, 10.0, 20.0) for p in PLAYERS)
    snaps = (
        Snapshot(1, 0, (52.5, 34.0), players),
        Snapshot(1, 300, (60.0, 34.0), players),
        Snapshot(2, 0, (52.5, 34.0), players),
    )
    m = Match(META, (), snaps)
    assert m.snapshots_at([(1, 300), (1, 100), (2, 0)]) == (snaps[1], snaps[2])


# --- validate_match frame by frame --------------------------------------------------------------


@pytest.mark.parametrize(
    ("dx", "dy", "ok"), [(80, 0, True), (81, 0, False), (48, 64, True), (48, 65, False)]
)
def test_every_step_keeps_his_own_top_speed_to_the_centimetres_rounding(dx, dy, ok):
    # 7.78 m/s for 100 ms plus 0.022 m for his two positions is 0.8 m exactly, in floats: a step
    # of 80 cm, straight or as 48 by 64, is on the bound and kept; 1 cm more is refused
    assert 7.78 * 0.1 + MOVE_TOLERANCE == 0.8
    m = match_of(kept([standing()], moving(1, dx, dy, frames=4)))
    speeds = dict.fromkeys(PLAYERS, 7.78)
    if ok:
        validate_match(m, speeds)
    else:
        refused(m, "m1 frame 2/100: cor-p01 moved faster than his 7.78 m/s", speeds)


def test_the_first_step_too_fast_is_named():
    rows = [standing() for _ in range(5)]
    for n, x in enumerate((1000, 1050, 1140, 1340, 1350)):  # 0.9 m, then 2 m: the first named
        rows[n][2 * 22] = x  # vel-p11
    refused(
        match_of(kept(rows, [standing()])),
        "m1 frame 1/200: vel-p11 moved faster than his 8.0",
        dict.fromkeys(PLAYERS, 8.0),
    )


@pytest.mark.parametrize(
    ("dx", "dy", "ok"), [(0, 95, True), (0, 96, False), (5, 95, True), (10, 95, False)]
)
def test_without_top_speeds_every_step_keeps_v1s_limit(dx, dy, ok):
    # 9.5 m/s plus 0.05 m/s is 95.5 cm a step: the centimetres either side of it, and 95.13 and
    # 95.52 cm askew, either side of the tolerance's half centimetre
    m = match_of(kept(moving(3, dx, dy, frames=3), [standing()]))
    if ok:
        validate_match(m)
    else:
        refused(m, "m1 frame 1/100: cor-p03 moved faster than 9.5 m/s")


@pytest.mark.parametrize(
    ("dx", "dy", "ok"), [(500, 0, True), (501, 0, False), (500, 20, True), (500, 25, False)]
)
def test_the_ball_keeps_its_own_top_speed_in_every_step(dx, dy, ok):
    # 50 m/s plus 0.05 m/s is 500.5 cm a step: the centimetres either side of it, and 500.40 and
    # 500.62 cm askew, either side of the tolerance's half centimetre
    m = match_of(kept(moving(0, -dx, dy, frames=3), [standing()]))
    if ok:
        validate_match(m, dict.fromkeys(PLAYERS, 9.0))
    else:
        refused(m, "m1 frame 1/100: the ball moved faster than 50.0 m/s")


@pytest.mark.parametrize(
    ("who", "axis", "value", "ok"),
    [
        (0, 0, 0, True),
        (0, 0, -1, False),
        (0, 0, 10500, True),
        (0, 0, 10501, False),
        (1, 1, 0, True),
        (1, 1, -1, False),
        (22, 1, 6800, True),
        (22, 1, 6801, False),
        (22, 0, 10500, True),
        (22, 0, 10501, False),
    ],
)
def test_everyone_and_the_ball_stay_on_the_pitch_in_every_frame(who, axis, value, ok):
    rows = [standing() for _ in range(3)]
    rows[1][2 * who + axis] = rows[2][2 * who + axis] = value
    rows[0][2 * who + axis] = value  # no step at all, only the place is judged
    m = match_of(kept([standing()], rows))
    name = "the ball" if who == 0 else PLAYERS[who - 1]
    if ok:
        validate_match(m)
    else:
        refused(m, f"m1 frame 2/0: {name} is off the pitch")


def test_a_frame_off_the_pitch_is_named_by_its_clock():
    rows = [standing() for _ in range(4)]
    rows[2][0] = rows[3][0] = 10501
    refused(match_of(kept(rows, [standing()])), "m1 frame 1/200: the ball is off the pitch")


def test_the_tracking_holds_the_two_lineups():
    swapped = (*PLAYERS[:-1], "vel-p12")
    refused(
        match_of(kept([standing()], [standing()], players=swapped)),
        "m1 tracking: players are not the two lineups",
    )
    refused(
        match_of(kept([standing()[:-2]], [standing()[:-2]], players=PLAYERS[:-1])),
        "m1 tracking: players are not the two lineups",
    )
    twice = [*standing(), 1000, 400]  # cor-p01 a second time: the same set, one name too many
    refused(
        match_of(kept([twice], [twice], players=(*PLAYERS, PLAYERS[0]))),
        "m1 tracking: players are not the two lineups",
    )


def test_a_match_keeps_snapshots_or_tracking_not_both():
    tracking = kept([standing()], [standing()])
    snaps = (tracking.snapshot(1, 0), tracking.snapshot(2, 0))
    refused(match_of(tracking, snapshots=snaps), "m1 tracking: a match keeps snapshots or tracking")


def test_the_tracking_covers_both_periods_in_whole_frames():
    ends = (
        Event("m1-e00000", 1, 0, EventType.PERIOD_END),
        Event("m1-e00001", 2, 0, EventType.PERIOD_END),
    )
    refused(Match(META, ends, (), kept([standing()])), "m1: tracking must cover both periods")
    broken = kept([standing()], [standing()])
    cut = Tracking(PLAYERS, (broken.periods[0], broken.periods[1][:-2]))
    refused(match_of(cut), "m1 tracking: period 2 is not 1-36001 whole frames")
    two = kept([standing()], [standing(), standing()])
    short = Tracking(PLAYERS, (two.periods[0], two.periods[1][:-2]))  # a frame and a bit
    refused(match_of(short), "m1 tracking: period 2 is not 1-36001 whole frames")
    empty = Tracking(PLAYERS, (broken.periods[0], b""))
    refused(match_of(empty), "m1 tracking: period 2 is not 1-36001 whole frames")


@pytest.mark.parametrize(("frames", "ok"), [(36_001, True), (36_002, False)])
def test_a_period_has_at_most_one_frame_a_100_ms_to_its_longest(frames, ok):
    assert MAX_PERIOD_MS // 100 + 1 == 36_001
    values = array("h", standing()) * frames
    tracking = Tracking(PLAYERS, (array("h", standing()).tobytes(), values.tobytes()))
    ends = (
        Event("m1-e00000", 1, 0, EventType.PERIOD_END),
        Event("m1-e00001", 2, MAX_PERIOD_MS, EventType.PERIOD_END),
    )
    m = Match(META, ends, (), tracking)
    if ok:
        validate_match(m)
    else:
        refused(m, "m1 tracking: period 2 is not 1-36001 whole frames")


def test_the_tracking_ends_at_each_period_end():
    tracking = kept(moving(1, 1, 0, frames=3), [standing()])
    early = Match(
        META,
        (
            Event("m1-e00000", 1, 100, EventType.PERIOD_END),
            Event("m1-e00001", 2, 0, EventType.PERIOD_END),
        ),
        (),
        tracking,
    )
    refused(early, "m1: tracking of period 1 must end at period_end")


def _recovery(x: float, y: float, clock_ms: int = 100) -> Event:
    return Event("m1-e00000", 1, clock_ms, EventType.RECOVERY, "cor", "cor-p01", Point(x, y))


def at_his_feet(ball_x: int = 1000) -> list[int]:
    """A frame with the ball at x = `ball_x` cm beside cor-p01, who stands at (10, 4)."""
    row = standing()
    row[0:2] = [ball_x, 400]
    return row


def test_every_event_is_where_the_frames_have_it():
    tracking = kept([at_his_feet(), at_his_feet()], [standing()])
    validate_match(match_of(tracking, _recovery(10.0, 4.0)))
    refused(match_of(tracking, _recovery(10.02, 4.0)), "m1-e00000: the ball is not at (10.02, 4.0)")
    refused(
        match_of(kept([at_his_feet(1100), at_his_feet(1100)], [standing()]), _recovery(11.0, 4.0)),
        "m1-e00000: cor-p01 is not at (11.0, 4.0) in tracking",
    )
    refused(match_of(tracking, _recovery(10.0, 4.0, 50)), "m1-e00000: no snapshot at 1/50")


# --- any tracking reads back as it was kept -----------------------------------------------------

cm_x = st.integers(0, 10500)
cm_y = st.integers(0, 6800)


@st.composite
def trackings(draw) -> Tracking:
    """One to four frames a period, everyone and the ball anywhere on the pitch."""
    periods = []
    for _ in (1, 2):
        rows = []
        for _ in range(draw(st.integers(1, 4))):
            row = []
            for _ in range(1 + len(PLAYERS)):
                row += [draw(cm_x), draw(cm_y)]
            rows.append(row)
        periods.append(rows)
    return kept(*periods)


@given(trackings())
def test_every_frame_reads_back_its_centimetres(tracking):
    m = match_of(tracking)
    frames = list(m.frames())
    assert len(frames) == tracking.count(1) + tracking.count(2)
    for f in frames:
        assert f.frame_id == make_frame_id("m1", f.period, f.clock_ms)
        values = tracking.values(f.period)
        at = f.clock_ms // 100 * tracking.width
        row = values[at : at + tracking.width].tolist()
        assert [round(f.ball.x * 100), round(f.ball.y * 100)] == row[:2]
        assert (f.ball.x, f.ball.y) == (row[0] / 100, row[1] / 100)
        assert [(p.player, p.x, p.y) for p in f.players] == [
            (pid, x / 100, y / 100) for pid, x, y in zip(PLAYERS, row[2::2], row[3::2], strict=True)
        ]
        s = tracking.snapshot(f.period, f.clock_ms)
        assert (s.ball, s.players) == (
            (f.ball.x, f.ball.y),
            tuple((p.player, p.x, p.y) for p in f.players),
        )
        assert m.frame_at(f.period, f.clock_ms) == f
    assert {(f.period, f.clock_ms) for f in frames} == {
        (p, c) for p in (1, 2, 3) for c in range(-100, 600, 50) if tracking.holds(p, c)
    }


# --- what the stats engine reads from the frames ------------------------------------------------


def test_a_pass_is_rated_from_the_frame_it_arrives_in():
    rows = [standing() for _ in range(3)]
    rows[1][2 * 12 : 2 * 12 + 2] = [1050, 400]  # vel-p01 half a metre from the arrival, early
    rows[2][2 * 12 : 2 * 12 + 2] = [1300, 400]  # and 3 m from it when the ball arrives
    m = match_of(kept(rows, [standing()]))
    e = Event(
        "m1-e00000", 1, 0, EventType.PASS, "cor", "cor-p02", Point(10.0, 7.0),
        end=Point(10.0, 4.0), duration_ms=200, outcome=Outcome.COMPLETE, recipient="cor-p01",
    )  # fmt: skip
    arrivals = _arrivals(m, [e])
    assert [(s.period, s.clock_ms) for s in arrivals] == [(1, 200)]
    (rating,) = pass_ratings(META, [e], arrivals)
    assert rating.opponent_m == 3.0


@pytest.mark.parametrize(
    ("x", "y", "ok"),
    [
        (0.0, 0.0, True),
        (105.0, 68.0, True),
        (-0.01, 1.0, False),
        (105.01, 1.0, False),
        (1.0, -0.01, False),
        (1.0, 68.01, False),
        (1, 1.0, True),  # an int is stored as a float
    ],
)
def test_a_frames_points_are_checked_on_the_fast_path_too(x, y, ok):
    if ok:
        for p in (Point(x, y), PlayerPosition("cor-p01", x, y)):
            assert (p.x, p.y) == (x, y) and type(p.x) is float and type(p.y) is float
    else:
        for make in (lambda: Point(x, y), lambda: PlayerPosition("cor-p01", x, y)):
            with pytest.raises(ValueError, match="is not a finite number"):
                make()

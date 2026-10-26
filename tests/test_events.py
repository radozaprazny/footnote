import json
import re

import pytest
from hypothesis import given
from hypothesis import strategies as st
from strategies import events, frame_clocks, frames, lineup, match_ids, match_metas, periods

from matchlens.events import (
    FRAME_MS,
    MAX_BALL_SPEED,
    MAX_PERIOD_MS,
    MAX_SEQ,
    MAX_TRAVEL_MS,
    SPECS,
    Event,
    EventType,
    MatchMeta,
    Outcome,
    Point,
    Restart,
    TrackingFrame,
    display_clock,
    frame_number,
    make_event_id,
    make_frame_id,
    parse_event_id,
    parse_frame_id,
    team_of,
)

# --- round trips: to_dict -> JSON -> from_dict gives the same object ---------------------------


@given(events())
def test_event_round_trips_through_json(event):
    assert Event.from_dict(json.loads(json.dumps(event.to_dict()))) == event


@given(frames())
def test_frame_round_trips_through_json(frame):
    assert TrackingFrame.from_dict(json.loads(json.dumps(frame.to_dict()))) == frame


@given(match_metas())
def test_match_meta_round_trips_through_json(meta):
    assert MatchMeta.from_dict(json.loads(json.dumps(meta.to_dict()))) == meta


@given(match_ids, st.integers(0, MAX_SEQ))
def test_event_id_round_trips(match_id, seq):
    event_id = make_event_id(match_id, seq)
    assert re.fullmatch(r"[a-z0-9]+-e[0-9]{5}", event_id)
    assert parse_event_id(event_id) == (match_id, seq)


@given(match_ids, periods, frame_clocks)
def test_frame_id_is_the_match_and_the_frame_number(match_id, period, clock_ms):
    assert parse_frame_id(make_frame_id(match_id, period, clock_ms)) == (
        match_id,
        frame_number(period, clock_ms),
    )


@given(periods, frame_clocks)
def test_frame_numbers_follow_time(period, clock_ms):
    """Consecutive frames have consecutive numbers, and period 2 continues after period 1."""
    n = frame_number(period, clock_ms)
    if clock_ms + FRAME_MS <= MAX_PERIOD_MS:
        assert frame_number(period, clock_ms + FRAME_MS) == n + 1
    if period == 2:
        assert n > frame_number(1, MAX_PERIOD_MS)


def plain(value) -> bool:
    """Only the types json.dumps writes natively: no enum members, tuples or dataclasses."""
    if type(value) is dict:
        return all(type(k) is str and plain(v) for k, v in value.items())
    if type(value) is list:
        return all(plain(v) for v in value)
    return value is None or type(value) in (str, int, float)


@given(events())
def test_to_dict_has_every_field_and_only_plain_types(event):
    d = event.to_dict()
    assert set(d) == set(Event.__dataclass_fields__)
    assert plain(d)


@given(frames(), match_metas())
def test_frame_and_meta_dicts_are_plain(frame, meta):
    assert plain(frame.to_dict()) and plain(meta.to_dict())


@given(events())
def test_ball_speed_is_within_the_cap_or_undefined(event):
    if SPECS[event.type].travels:
        assert 0 <= event.ball_speed() <= MAX_BALL_SPEED
    else:
        with pytest.raises(ValueError, match="has no ball path"):
            event.ball_speed()


def test_ball_speed_example():
    shot = Event.from_dict(valid_pass() | {"start": {"x": 0, "y": 0}, "end": {"x": 30, "y": 0}})
    assert shot.ball_speed() == 25.0  # 30 m in 1.2 s


def test_points_become_floats():
    assert Point(52, 34) == Point(52.0, 34.0)
    assert isinstance(Point(52, 34).x, float)


@pytest.mark.parametrize("bad", ["corp07", "cor-", "-p07", "cor-p07-x", "COR-p07", 5, None])
def test_team_of_rejects_bad_ids(bad):
    with pytest.raises(ValueError, match="is not a player id like cor-p07"):
        team_of(bad)


def test_team_of():
    assert team_of("cor-p07") == "cor"


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: make_event_id("M7", 1), "is not a match id like m7"),
        (lambda: make_event_id("m7", MAX_SEQ + 1), "seq = 100000 is not an int in 0-99999"),
        (lambda: make_event_id("m7", True), "seq = True is not an int"),
        (lambda: make_frame_id("m7", 3, 0), "period = 3 is not one of"),
        (lambda: make_frame_id("m7", 1, 150), "clock_ms 150 is not a multiple of 100"),
        (lambda: parse_event_id("m7-e٠٠٠٤٢"), "is not an event id like m7-e00042"),
        (lambda: parse_frame_id("m7-e00042"), "is not a frame id like m7-f000123"),
    ],
    ids=lambda x: "" if callable(x) else x,
)
def test_id_helpers_refuse_bad_input(call, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        call()


# --- broadcast clock ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "clock_ms", "shown"),
    [
        (1, 0, "00:00"),
        (1, 754_000, "12:34"),
        (1, 44 * 60_000 + 59_999, "44:59"),
        (1, 45 * 60_000, "45+0:00"),
        (1, 45 * 60_000 + 133_000, "45+2:13"),
        (2, 0, "45:00"),
        (2, 22 * 60_000 + 23_000, "67:23"),
        (2, 45 * 60_000 + 181_000, "90+3:01"),
    ],
)
def test_display_clock_examples(period, clock_ms, shown):
    assert display_clock(period, clock_ms) == shown


@given(periods, st.integers(0, MAX_PERIOD_MS))
def test_display_clock_shows_the_elapsed_match_time(period, clock_ms):
    shown = display_clock(period, clock_ms)
    assert re.fullmatch(r"\d{2}:\d{2}|(45|90)\+\d+:\d{2}", shown)
    numbers = [int(n) for n in re.findall(r"\d+", shown)]  # mm, ss  or  45/90, m, ss
    minutes, seconds = sum(numbers[:-1]), numbers[-1]
    assert minutes * 60 + seconds == (period - 1) * 45 * 60 + clock_ms // 1000


@pytest.mark.parametrize(("period", "clock_ms"), [(3, 0), (1, -1), (1, MAX_PERIOD_MS + 1)])
def test_display_clock_rejects_bad_input(period, clock_ms):
    with pytest.raises(ValueError):
        display_clock(period, clock_ms)


# --- broken rules: each raises ValueError with a message that names the rule -------------------


def valid_pass() -> dict:
    return {
        "event_id": "m7-e00042",
        "period": 1,
        "clock_ms": 754_000,
        "type": "pass",
        "team": "cor",
        "player": "cor-p07",
        "start": {"x": 52.0, "y": 34.0},
        "end": {"x": 60.0, "y": 40.0},
        "outcome": "complete",
        "restart": None,
        "duration_ms": 1200,
        "recipient": "cor-p09",
        "related": None,
    }


def valid_tackle() -> dict:
    return valid_pass() | {
        "type": "tackle",
        "end": None,
        "duration_ms": None,
        "outcome": "won",
        "recipient": None,
    }


def valid_goal() -> dict:
    return valid_tackle() | {"type": "goal", "outcome": None, "related": "m7-e00041"}


def _set(**changes):
    def apply(d):
        d.update(changes)

    return apply


def _period_end_with_team(d):
    d.update(type="period_end", player=None, start=None, end=None, duration_ms=None, outcome=None)
    d.update(recipient=None)


def _start_missing_y(d):
    d["start"] = {"x": 1.0}


def _start_not_finite(d):
    d["start"] = {"x": float("nan"), "y": 1.0}


def _start_too_big_for_a_float(d):
    d["start"] = {"x": 10**400, "y": 1.0}


def _too_fast(d):
    d.update(start={"x": 0.0, "y": 0.0}, end={"x": 105.0, "y": 68.0}, duration_ms=1)


def _travels_past_the_period(d):
    d.update(clock_ms=MAX_PERIOD_MS - 1000, duration_ms=1200)


def _travels_to_the_period_limit(d):
    d.update(clock_ms=MAX_PERIOD_MS - 1200, duration_ms=1200)


def _exactly_the_speed_cap(d):
    d.update(start={"x": 0.0, "y": 0.0}, end={"x": 50.0, "y": 0.0}, duration_ms=1000)


def _just_over_the_speed_cap(d):
    d.update(start={"x": 0.0, "y": 0.0}, end={"x": 50.0, "y": 0.0}, duration_ms=999)


def _key_that_is_not_a_string(d):
    d[1] = "x"


def _unknown_key(d):
    d["foo"] = 1


def _missing_key(d):
    del d["team"]


BROKEN_EVENTS = [
    (valid_pass, _set(event_id="m7-e42"), "is not an event id like m7-e00042"),
    (valid_pass, _set(event_id="M7-e00042"), "is not an event id like m7-e00042"),
    (valid_pass, _set(period=3), "period = 3 is not one of"),
    (valid_pass, _set(period=True), "period = True is not one of"),
    (valid_pass, _set(clock_ms=-1), "clock_ms = -1 is not an int"),
    (valid_pass, _set(clock_ms=MAX_PERIOD_MS + 1), "clock_ms = 3600001 is not an int"),
    (valid_pass, _set(clock_ms=1.5), "clock_ms = 1.5 is not an int"),
    (valid_pass, _set(type="dribble"), "'dribble' is not a valid EventType"),
    (valid_pass, _set(type=None), "type is required"),
    (valid_pass, _set(end=None), "pass needs end and duration_ms"),
    (valid_pass, _set(duration_ms=None), "pass needs end and duration_ms"),
    (valid_pass, _set(duration_ms=0), "duration_ms = 0 is not an int in 1-10000"),
    (valid_pass, _set(duration_ms=MAX_TRAVEL_MS + 1), "duration_ms = 10001 is not an int"),
    (valid_pass, _set(duration_ms=True), "duration_ms = True is not an int"),
    (valid_pass, _too_fast, "m/s is over 50"),
    (valid_pass, _just_over_the_speed_cap, "ball speed 50.1 m/s is over 50"),
    (valid_pass, _exactly_the_speed_cap, None),
    (valid_pass, _travels_past_the_period, "still travelling after the period limit"),
    (valid_pass, _travels_to_the_period_limit, None),
    (valid_pass, _set(outcome="won"), "pass outcome must be one of complete, incomplete, out"),
    (valid_pass, _set(outcome=None), "pass outcome must be one of"),
    (valid_pass, _set(outcome="brilliant"), "'brilliant' is not a valid Outcome"),
    (valid_pass, _set(restart="half_time"), "'half_time' is not a valid Restart"),
    (
        valid_pass,
        _set(type="shot", outcome="goal", recipient=None, restart="throw_in"),
        "shot cannot be a throw_in restart",
    ),
    (valid_pass, _set(type="shot", outcome="goal", recipient=None, restart="goal_kick"), None),
    (valid_pass, _set(team="COR"), "'COR' is not a club id"),
    (valid_pass, _set(team=None), "pass needs team, player and start"),
    (valid_pass, _set(player="vel-p01"), "player 'vel-p01' is not in team cor"),
    (valid_pass, _set(player="corp01"), "player 'corp01' is not in team cor"),
    (valid_pass, _set(player="cor-p07-x"), "player 'cor-p07-x' is not in team cor"),
    (valid_pass, _set(recipient=None), "a complete pass needs a recipient"),
    (valid_pass, _set(recipient="cor-p07"), "recipient cor-p07 is the player"),
    (valid_pass, _set(recipient="vel-p01"), "recipient: player 'vel-p01' is not in team cor"),
    (valid_pass, _set(outcome="out"), "only a complete pass or clearance has a recipient"),
    (valid_pass, _set(related="m7-e00001"), "pass must not have related"),
    (valid_pass, _set(start={"x": 105.5, "y": 1.0}), "x = 105.5 is not a finite number in 0-105"),
    (valid_pass, _set(end={"x": 1.0, "y": -0.1}), "y = -0.1 is not a finite number in 0-68"),
    (valid_pass, _set(start={"x": "10", "y": 1.0}), "x = '10' is not a finite number"),
    (valid_pass, _set(start={"x": True, "y": 1.0}), "x = True is not a finite number"),
    (valid_pass, _start_not_finite, "x = nan is not a finite number"),
    (valid_pass, _start_too_big_for_a_float, "is not a finite number in 0-105"),
    (valid_pass, _start_missing_y, "start: expected a point with x and y"),
    (valid_pass, _unknown_key, "unknown keys: foo"),
    (valid_pass, _key_that_is_not_a_string, "unknown keys: 1"),
    (valid_pass, _missing_key, "missing keys: team"),
    (valid_tackle, _set(end={"x": 1.0, "y": 1.0}), "tackle must not have end or duration_ms"),
    (valid_tackle, _set(restart="throw_in"), "tackle cannot be a throw_in restart"),
    (valid_tackle, _set(type="interception", outcome="won"), "must not have an outcome"),
    (valid_tackle, _set(outcome="complete"), "tackle outcome must be one of lost, won"),
    (valid_tackle, _set(recipient="cor-p09"), "only a complete pass or clearance has a recipient"),
    (valid_tackle, _period_end_with_team, "period_end must not have team"),
    (valid_goal, _set(player=None), "goal needs team, player and start"),
    (valid_goal, _set(related=None), "goal needs related, the event id of its shot"),
    (valid_goal, _set(related="m8-e00001"), "related m8-e00001 is not an earlier event"),
    (valid_goal, _set(related="m7-e00042"), "related m7-e00042 is not an earlier event"),
    (valid_goal, _set(related="shot"), "'shot' is not an event id like m7-e00042"),
    (valid_goal, _set(type="save", team="vel", player="vel-p01"), None),  # valid: a save
]


@pytest.mark.parametrize(("base", "breaker", "message"), BROKEN_EVENTS, ids=lambda x: "")
def test_broken_event_is_refused(base, breaker, message):
    data = base()
    breaker(data)
    if message is None:
        Event.from_dict(data)
        return
    with pytest.raises(ValueError, match=re.escape(message)):
        Event.from_dict(data)


def test_from_dict_needs_an_object():
    with pytest.raises(ValueError, match="Event must be a JSON object, got list"):
        Event.from_dict([])


def test_constructor_checks_point_types():
    with pytest.raises(ValueError, match="start must be a Point"):
        Event("m7-e00001", 1, 0, "tackle", "cor", "cor-p01", (1, 2), outcome="won")


def test_every_event_type_has_a_spec_and_period_end_is_the_only_actorless_type():
    assert set(SPECS) == set(EventType)
    assert [t for t, s in SPECS.items() if not s.actor] == [EventType.PERIOD_END]


def test_enum_members_coerce_from_strings():
    event = Event.from_dict(valid_pass() | {"restart": "corner"})
    assert event.type is EventType.PASS
    assert event.outcome is Outcome.COMPLETE
    assert event.restart is Restart.CORNER


# --- tracking frames ----------------------------------------------------------------------------


def valid_frame() -> dict:
    players = [{"player": p, "x": 10.0, "y": 20.0} for p in lineup("cor") + lineup("vel")]
    return {
        "frame_id": make_frame_id("m7", 2, 1_234_500),
        "period": 2,
        "clock_ms": 1_234_500,
        "players": players,
        "ball": {"x": 52.5, "y": 34.0},
    }


def _drop_a_player(d):
    d["players"].pop()


def _duplicate_player(d):
    d["players"][1]["player"] = d["players"][0]["player"]


def _twelve_cor(d):
    d["players"][-1]["player"] = "cor-p12"


def _three_teams(d):
    d["players"][-1]["player"] = "qrd-p01"


def _player_off_pitch(d):
    d["players"][3]["x"] = 105.01


def _player_without_coordinates(d):
    d["players"][3] = {"player": "cor-p04"}


def _player_id_not_a_string(d):
    d["players"][3]["player"] = 5


BROKEN_FRAMES = [
    (_set(frame_id="m7-e00042"), "is not a frame id like m7-f000123"),
    (_set(frame_id="m7-f048344"), "frame number 48344 does not match the period and clock"),
    (_set(clock_ms=1_234_550), "clock_ms 1234550 is not a multiple of 100"),
    (_set(clock_ms=-100), "clock_ms = -100 is not an int"),
    (_set(period=0), "period = 0 is not one of"),
    (_drop_a_player, "21 players, expected 22"),
    (_duplicate_player, "duplicate player: cor-p01"),
    (_twelve_cor, "cor has 12 players, expected 11"),
    (_three_teams, "3 teams on the pitch, expected 2"),
    (_player_off_pitch, "cor-p04: x = 105.01 is not a finite number in 0-105"),
    (_player_without_coordinates, "expected a player position with player, x and y"),
    (_player_id_not_a_string, "5 is not a player id like cor-p07"),
    (_set(players="none"), "players must be a list"),
    (_set(ball={"x": 1.0, "y": 68.5}), "ball: y = 68.5 is not a finite number in 0-68"),
    (_set(ball=None), "ball must be a Point"),
    (_set(extra=1), "unknown keys: extra"),
    (_key_that_is_not_a_string, "unknown keys: 1"),
]


@pytest.mark.parametrize(("breaker", "message"), BROKEN_FRAMES, ids=lambda x: "")
def test_broken_frame_is_refused(breaker, message):
    data = valid_frame()
    breaker(data)
    with pytest.raises(ValueError, match=re.escape(message)):
        TrackingFrame.from_dict(data)


def test_frame_number_is_in_its_id():
    frame = TrackingFrame.from_dict(valid_frame())
    assert frame.frame_id == "m7-f048346"  # 36001 frames of period 1, then 12345 of period 2
    assert parse_frame_id(frame.frame_id)[1] == frame_number(frame.period, frame.clock_ms)


def test_frame_constructor_checks_player_types():
    with pytest.raises(ValueError, match="players must be PlayerPosition objects"):
        TrackingFrame("m7-f000000", 1, 0, [1] * 22, Point(1, 1))
    with pytest.raises(ValueError, match="players must be a list"):
        TrackingFrame("m7-f000000", 1, 0, None, Point(1, 1))


# --- match metadata -----------------------------------------------------------------------------


def valid_meta() -> dict:
    return {
        "match_id": "m7",
        "home": "cor",
        "away": "vel",
        "home_lineup": list(lineup("cor")),
        "away_lineup": list(lineup("vel")),
        "seed": 7,
    }


def _ten_at_home(d):
    d["home_lineup"].pop()


def _away_player_at_home(d):
    d["home_lineup"][0] = "vel-p01"


def _twice_in_lineup(d):
    d["away_lineup"][1] = d["away_lineup"][0]


def _unhashable_in_lineup(d):
    d["away_lineup"][1] = []


BROKEN_METAS = [
    (_set(match_id="M7"), "is not a match id like m7"),
    (_set(match_id="m-7"), "is not a match id like m7"),
    (_set(away="cor"), "home and away are both cor"),
    (_set(home="Cor"), "'Cor' is not a club id"),
    (_ten_at_home, "home_lineup has 10 players, expected 11"),
    (_away_player_at_home, "home_lineup: player 'vel-p01' is not in team cor"),
    (_twice_in_lineup, "duplicate player in away_lineup: vel-p01"),
    (_unhashable_in_lineup, "away_lineup: player [] is not in team vel"),
    (_set(away_lineup="vel-p01"), "away_lineup must be a list"),
    (_set(home_lineup=None), "home_lineup must be a list"),
    (_set(seed=-1), "seed = -1 is not an int"),
    (_set(seed=True), "seed = True is not an int"),
    (_set(seed=2**63), "seed = 9223372036854775808 is not an int"),
    (_key_that_is_not_a_string, "unknown keys: 1"),
]


@pytest.mark.parametrize(("breaker", "message"), BROKEN_METAS, ids=lambda x: "")
def test_broken_meta_is_refused(breaker, message):
    data = valid_meta()
    breaker(data)
    with pytest.raises(ValueError, match=re.escape(message)):
        MatchMeta.from_dict(data)

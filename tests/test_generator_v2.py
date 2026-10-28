"""Generator v2 (M9 item 5): v1's decisions over players who move. Every match agrees with its
tracking at every event and keeps each player's own top speed (`validate_match`), takes every
restart with everyone keeping the Laws, and keeps the calibration's match-level numbers."""

import dataclasses
import hashlib
import math
import os
import random
import statistics
import subprocess
import sys
from collections import Counter
from multiprocessing import get_context

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from strategies import two_clubs

import matchlens.generator_v2 as generator_v2
from matchlens.events import FRAME_MS, EventType, Outcome, Restart
from matchlens.formations import FORMATIONS, ROLE_GROUP
from matchlens.generator_v2 import (
    CONTROL_M,
    DUEL_M,
    GLIDE_SPEED,
    MIN_FLIGHT_MS,
    RECOVER_AFTER_MS,
    REFRESH_EVERY,
    _ceil_ms,
    _centi,
    _flight_ms,
    _new_sim,
    generate_match_v2,
    pick_lineup,
)
from matchlens.league import load_league
from matchlens.match import MOVE_TOLERANCE, attacking_goal_x, validate_match
from matchlens.movement import Body, Limits
from matchlens.setpieces import layout

CALIBRATION_SEEDS = range(50)
CLUBS = {c.id: c for c in load_league().clubs}
PLAYERS = {p.id: p for c in CLUBS.values() for p in c.players}
ROUNDING = 0.015  # m: two positions stored to the centimetre


@pytest.fixture(scope="module")
def matches():
    """The calibration's 50 matches. A v2 match takes about 9 s, so they are made in parallel."""
    workers = max(1, min(4, os.cpu_count() or 1))
    with get_context("spawn").Pool(workers) as pool:
        return pool.map(generate_match_v2, CALIBRATION_SEEDS)


def top_speeds(m):
    return {pid: PLAYERS[pid].top_speed for pid in m.meta.home_lineup + m.meta.away_lineup}


def digest(m):
    """The whole match: its meta and events, and every frame of its tracking."""
    h = hashlib.sha256(repr((m.meta, m.events, m.snapshots, m.tracking)).encode())
    for values in m.tracking.periods:
        h.update(values)
    return h.hexdigest()


# --- the approved generator properties, for v2 --------------------------------------------------


def test_every_match_agrees_with_its_tracking_and_each_players_own_top_speed(matches):
    for seed, m in zip(CALIBRATION_SEEDS, matches, strict=True):
        assert m.meta.match_id == f"m{seed}"  # v1's ids
        validate_match(m, top_speeds(m))


@given(st.integers(0, 2**63 - 1), two_clubs)
@settings(max_examples=2, deadline=None)
def test_any_seed_and_clubs_give_a_valid_match(seed, clubs):
    home, away = clubs
    m = generate_match_v2(seed, home=home, away=away)  # it validates its match itself
    assert (m.meta.home, m.meta.away, m.meta.match_id) == (home, away, f"m{seed}{home}{away}")
    validate_match(m, top_speeds(m))


def test_the_same_seed_gives_the_same_match(matches):
    assert generate_match_v2(0) == matches[0]
    assert matches[0].events != matches[1].events


def test_the_same_match_across_processes_and_hash_seeds(matches):
    """Set iteration order must not leak into the match."""
    code = (
        "import hashlib; from matchlens.generator_v2 import generate_match_v2;"
        "m = generate_match_v2(1);"
        "h = hashlib.sha256(repr((m.meta, m.events, m.snapshots, m.tracking)).encode());"
        "[h.update(values) for values in m.tracking.periods];"
        "print(h.hexdigest())"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONHASHSEED": "1"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == digest(matches[1])


def test_calibration_over_50_seeds(matches):
    """Match-level numbers in football-realistic ranges (means over the seeds): v1's ranges."""
    per_match = []
    for m in matches:
        passes = [e for e in m.events if e.type is EventType.PASS]
        counts = Counter(e.type for e in m.events)
        restarts = Counter(e.restart for e in m.events if e.restart is not None)
        per_match.append(
            {
                "passes": len(passes),
                "accuracy": sum(e.outcome is Outcome.COMPLETE for e in passes) / len(passes),
                "shots": counts[EventType.SHOT],
                "goals": counts[EventType.GOAL],
                "fouls": counts[EventType.FOUL],
                "throw_ins": restarts["throw_in"],
                "corners": restarts["corner"],
            }
        )
    means = {k: statistics.mean(row[k] for row in per_match) for k in per_match[0]}
    targets = {
        "passes": (850, 1350),
        "accuracy": (0.78, 0.90),
        "shots": (15, 32),
        "goals": (1.5, 4.0),
        "fouls": (12, 40),
        "throw_ins": (15, 50),
        "corners": (2, 12),
    }
    for key, (low, high) in targets.items():
        assert low <= means[key] <= high, f"{key}: mean {means[key]:.2f} not in {low}-{high}"
    assert max(row["goals"] for row in per_match) <= 9


# --- events on the movement's 100 ms steps -------------------------------------------------------


def test_every_event_lies_on_the_100_ms_grid_and_every_step_is_kept(matches):
    for m in matches:
        for e in m.events:
            assert e.clock_ms % FRAME_MS == 0, e.event_id
            assert (e.duration_ms or 0) % FRAME_MS == 0, e.event_id
        # a frame at every step from the kick-off to the period's end, and no snapshot
        assert m.snapshots == ()
        ends = {e.period: e.clock_ms for e in m.events if e.type is EventType.PERIOD_END}
        assert {p: m.tracking.count(p) for p in (1, 2)} == {
            p: end // FRAME_MS + 1 for p, end in ends.items()
        }


def _at(m, e):
    snap = m.tracking.snapshot(e.period, e.clock_ms)
    return {pid: (x, y) for pid, x, y in snap.players}


def _side(m, team):
    return m.meta.home_lineup if team == m.meta.home else m.meta.away_lineup


def _holder_before(events, i):
    """Who had the ball before event `i`, by the events: a completed pass's or clearance's
    recipient, or whoever won it (an interception, a recovery, a save, a regain, a won tackle);
    a challenge the carrier withstood leaves it with him."""
    for e in reversed(events[:i]):
        if e.type in (EventType.PASS, EventType.CLEARANCE):
            return e.recipient if e.outcome is Outcome.COMPLETE else None
        if e.type in (EventType.INTERCEPTION, EventType.RECOVERY, EventType.SAVE):
            return e.player
        if (e.type, e.outcome) in (
            (EventType.PRESSURE, Outcome.REGAIN),
            (EventType.TACKLE, Outcome.WON),
        ):
            return e.player
        if e.type not in (EventType.PRESSURE, EventType.TACKLE):
            return None
    return None


def test_a_challenge_comes_from_within_1_5_m_of_the_carrier(matches):
    challenges = 0
    for m in matches:
        for i, e in enumerate(m.events):
            if e.type not in (EventType.PRESSURE, EventType.TACKLE, EventType.FOUL):
                continue
            challenges += 1
            holder = _holder_before(m.events, i)
            assert holder is not None and holder not in _side(m, e.team), e.event_id
            at = _at(m, e)
            assert math.dist(at[e.player], at[holder]) <= DUEL_M + ROUNDING, e.event_id
    assert challenges > 0


def test_a_loose_ball_is_recovered_where_it_lies_after_half_a_second(matches):
    loose = (Outcome.INCOMPLETE, Outcome.BLOCKED, Outcome.WOODWORK)
    recoveries = 0
    for m in matches:
        for prev, e in zip(m.events, m.events[1:], strict=False):
            if e.type is not EventType.RECOVERY:
                continue
            recoveries += 1
            assert prev.end is not None and prev.outcome in loose, e.event_id
            landed = prev.clock_ms + prev.duration_ms
            assert e.clock_ms >= landed + RECOVER_AFTER_MS, e.event_id
            gap = math.dist((e.start.x, e.start.y), (prev.end.x, prev.end.y))
            assert gap <= CONTROL_M + ROUNDING, e.event_id
    assert recoveries > 0


# --- the Laws at every restart, checked here on their own -----------------------------------------


def _laws_broken(m, e):
    """Who breaks the Laws in the snapshot of restart `e` (taken by `e.team`); a centimetre's
    rounding is allowed, the margin `setpieces.layout` keeps beyond the Laws is not needed."""
    at = _at(m, e)
    mine, theirs = _side(m, e.team), [p for p in at if p not in _side(m, e.team)]
    goal_x = attacking_goal_x(m.meta, e.team, e.period)  # the goal the taker attacks
    own_x = 105.0 - goal_x
    spot = (e.start.x, e.start.y)

    def ahead(p, team_goal_x):  # how far into the half its team attacks
        return at[p][0] - 52.5 if team_goal_x == 105.0 else 52.5 - at[p][0]

    def in_area(p, line_x):
        return abs(at[p][0] - line_x) <= 16.5 and abs(at[p][1] - 34.0) <= 20.16

    def near(p, centre, d):
        return math.dist(at[p], centre) < d - ROUNDING

    keeper = next(p for p in theirs if PLAYERS[p].role == "GK")
    if e.restart is Restart.KICK_OFF:
        broken = [p for p in mine if ahead(p, goal_x) > ROUNDING]
        broken += [p for p in theirs if ahead(p, own_x) > ROUNDING or near(p, (52.5, 34.0), 9.15)]
    elif e.restart is Restart.GOAL_KICK:
        broken = [p for p in theirs if in_area(p, own_x)]
    elif e.restart is Restart.CORNER:
        broken = [p for p in theirs if near(p, spot, 10.15)]
    elif e.restart is Restart.THROW_IN:
        broken = [p for p in theirs if near(p, spot, 2.0)]
    elif e.restart is Restart.FREE_KICK:
        own_area = abs(spot[0] - own_x) <= 16.5 and abs(spot[1] - 34.0) <= 20.16
        broken = [p for p in theirs if near(p, spot, 9.15) or (own_area and in_area(p, own_x))]
    else:  # a penalty: the keeper on his line, the rest outside the area and the arc, behind
        broken = [] if abs(at[keeper][0] - goal_x) <= 0.011 else [keeper]
        for p in at:
            if p in (e.player, keeper):
                continue
            behind = (at[p][0] - spot[0]) * (1 if goal_x == 105.0 else -1) <= ROUNDING
            if in_area(p, goal_x) or near(p, spot, 9.15) or not behind:
                broken.append(p)
    return broken


def test_every_restart_is_played_with_everyone_keeping_the_laws(matches):
    kinds = Counter()
    for m in matches:
        for e in m.events:
            if e.restart is None:
                continue
            kinds[e.restart] += 1
            assert _laws_broken(m, e) == [], (e.event_id, e.restart)
            # the taker on the spot, a thrower and a corner taker on the line itself
            assert _at(m, e)[e.player] == (e.start.x, e.start.y)
    assert set(kinds) == set(Restart), kinds


# --- the lineup ----------------------------------------------------------------------------------


@pytest.mark.parametrize("club", sorted(CLUBS))
@pytest.mark.parametrize("seed", range(5))
def test_each_slot_gets_a_player_of_its_role_and_its_side_if_one_is_free(club, seed):
    slots, keeper = pick_lineup(random.Random(seed), CLUBS[club])
    squad = {p.id: p for p in CLUBS[club].players}
    assert squad[keeper].role == "GK" and keeper not in slots
    assert list(slots.values()) == list(FORMATIONS[CLUBS[club].formation])
    for pid, slot in slots.items():
        assert squad[pid].role == slot.role, pid
        if squad[pid].side != slot.side:  # every player of the role and that side plays already
            free = [p for p in squad.values() if p.id not in slots and p.role == slot.role]
            assert all(p.side != slot.side for p in free), pid


def test_a_missing_role_is_covered_by_its_group_and_a_missing_group_is_refused():
    club = CLUBS["cor"]  # 4-3-3, one DM slot
    no_dm = [dataclasses.replace(p, role="CM") if p.role == "DM" else p for p in club.players]
    slots, _ = pick_lineup(random.Random(0), dataclasses.replace(club, players=tuple(no_dm)))
    dm = next(pid for pid, s in slots.items() if s.role == "DM")
    assert ROLE_GROUP[next(p for p in no_dm if p.id == dm).role] == "midfield"
    no_attack = tuple(p for p in club.players if ROLE_GROUP[p.role] != "attack")
    with pytest.raises(ValueError, match="cor: no player left for a W of 4-3-3"):
        pick_lineup(random.Random(0), dataclasses.replace(club, players=no_attack))
    no_keeper = tuple(p for p in club.players if p.role != "GK")
    with pytest.raises(ValueError, match="cor: no keeper"):
        pick_lineup(random.Random(0), dataclasses.replace(club, players=no_keeper))


# --- the decisions' boundaries, on a match set up by hand -----------------------------------------


def _set_up(seed=0):
    """A match before its kick-off, everyone apart: the home side (attacking x = 105 in the first
    half) at x = 30, the away side at x = 75."""
    sim = _new_sim(seed)
    sim.start_period(1)
    sim.tired_now()
    for i, pid in enumerate(sim.meta.home_lineup):
        sim.bodies[pid] = Body(30.0, 4.0 + 6.0 * i)
    for i, pid in enumerate(sim.meta.away_lineup):
        sim.bodies[pid] = Body(75.0, 4.0 + 6.0 * i)
    sim.pending = None
    return sim


@pytest.mark.parametrize(("gap", "challenges"), [(1.5, True), (1.51, False)])
def test_an_opponent_challenges_from_1_5_m_never_a_keeper(gap, challenges):
    sim = _set_up()
    carrier = sim.meta.home_lineup[5]
    rival, keeper = sim.meta.away_lineup[5], sim.meta.away_lineup[0]
    sim.bodies[carrier] = Body(50.0, 34.0)
    sim.take(carrier)
    sim.ball = (50.0, 34.0)
    sim.bodies[keeper] = Body(50.0, 33.0)  # 1 m off, but a keeper does not challenge
    sim.bodies[rival] = Body(50.0, 34.0 + gap)
    assert sim.challenger(carrier) == (rival if challenges else None)


@pytest.mark.parametrize(("gap", "reached"), [(0.75, True), (0.76, False)])
def test_a_resting_ball_is_taken_from_0_75_m(gap, reached):
    sim = _set_up()
    player = sim.meta.home_lineup[3]
    sim.bodies[player] = Body(50.0, 34.0)
    assert sim.reached(player, (50.0 + gap, 34.0)) is reached


class _Scripted:
    """A stand-in for random.Random that never scores outright and always chooses a save."""

    def random(self):
        return 0.99

    def choices(self, population, weights=None):
        return [population[0]]

    def uniform(self, a, b):
        return (a + b) / 2

    def choice(self, seq):
        return seq[0]


@pytest.mark.parametrize(("beyond", "expected"), [(-0.001, EventType.SAVE), (0.01, EventType.GOAL)])
def test_a_keeper_who_cannot_reach_the_save_at_his_own_top_speed_concedes(beyond, expected):
    sim = _set_up()
    striker = sim.meta.home_lineup[10]
    keeper = sim.meta.away_lineup[0]
    sim.bodies[striker] = Body(89.0, 34.0)
    sim.take(striker)
    sim.ball = (89.0, 34.0)
    # the shot aims at (104, 37.5) for a keeper above y = 37.5: he stands off its line, square to
    # it from a point 90 % of the way, as far as his top speed covers in the ball's flight
    start, aim = (89.0, 34.0), (104.0, 37.5)
    length = math.dist(start, aim)
    ux, uy = (aim[0] - start[0]) / length, (aim[1] - start[1]) / length
    save = (start[0] + 0.9 * length * ux, start[1] + 0.9 * length * uy)
    ms = _flight_ms(start, save, 25.0)  # _Scripted's speed: the middle of 18-32 m/s
    reach = PLAYERS[keeper].top_speed * ms / 1000 + beyond
    sim.bodies[keeper] = Body(save[0] - uy * reach, save[1] + ux * reach)
    assert sim.bodies[keeper].y > 37.5
    sim.rng = _Scripted()
    sim.shoot()
    assert sim.events[-1].type is expected
    assert sim.events[-2].type is EventType.SHOT


def test_flights_lie_on_the_grid_never_faster_than_kicked():
    assert _ceil_ms(0.1 + 0.2) == 300  # a float's last bit adds no step
    assert _ceil_ms(0.301) == 400
    assert _flight_ms((0.0, 0.0), (1.0, 0.0), 20.0) == MIN_FLIGHT_MS == 300
    assert _flight_ms((0.0, 0.0), (20.0, 0.0), 20.0) == 1000
    assert _flight_ms((0.0, 0.0), (20.01, 0.0), 20.0) == 1100
    assert _flight_ms((0.0, 0.0), (104.0, 0.0), 9.0) == 10_000  # the schema's longest


def test_the_constants_are_the_plans():
    # PROGRESS, M9 item 5: a challenge from within 1.5 m, aims refreshed every third step
    assert (DUEL_M, REFRESH_EVERY) == (1.5, 3)
    assert (CONTROL_M, RECOVER_AFTER_MS) == (0.75, 500)
    assert GLIDE_SPEED == 8.0


@pytest.mark.parametrize(("beyond", "saves"), [(0.0, True), (0.01, False)])
def test_a_keeper_reaches_a_save_exactly_at_his_own_top_speed(beyond, saves):
    # in 0.5 s exactly half his top speed in metres (both exact in floats), or a centimetre more
    sim = _set_up()
    keeper = sim.meta.away_lineup[0]
    top = sim.limits[keeper].top_speed
    assert top == PLAYERS[keeper].top_speed  # not tired at the kick-off
    sim.bodies[keeper] = Body(100.0, 0.0)
    assert sim.reaches_save(keeper, (100.0, top * 0.5 + beyond), 500) is saves


@pytest.mark.parametrize("breaking_until", [0, 40_000])
def test_a_restart_waits_while_anyone_breaks_the_laws(monkeypatch, breaking_until):
    # a throw-in at 10 s: its pause (5-12 s) and its taker's run are over well before 40 s, so
    # only someone breaking the Laws until then can hold it back to 40 s
    sim = _set_up()
    spot = (60.0, 0.0)
    sim.t, sim.ball = 10_000, spot
    sim.pending = (Restart.THROW_IN, spot, sim.meta.home, None)
    asked = []

    def breaking(kind, where, taker, taking, other, at):
        asked.append(sim.t)
        return ["somebody"] if sim.t < breaking_until else []

    monkeypatch.setattr(generator_v2, "breaches", breaking)
    sim.restart()
    throw = next(e for e in sim.events if e.restart is Restart.THROW_IN)
    if breaking_until:
        assert throw.clock_ms == breaking_until == asked[-1]
    else:
        assert throw.clock_ms < 40_000


def _all_set(monkeypatch, kind, spot, pause=0):
    """A restart at 10 s with everyone already on his point of its layout and the ball on the
    spot, so that nothing holds it back but what a test moves off; `pause` in seconds."""
    monkeypatch.setitem(generator_v2.PAUSES, kind, (pause, pause))
    sim = _set_up()
    team = sim.meta.home  # attacks x = 105 in the first half
    taking, other = sim.team(team), sim.team(sim.opponent(team))
    taker = sim.taker(kind, spot, team) if kind is not Restart.PENALTY else sim.meta.home_lineup[10]
    aims = layout(kind, spot, taker, taking, other, sim.positions(), sim.tired_now())
    for pid, aim in aims.items():
        sim.bodies[pid] = Body(*aim.point)
    sim.t, sim.ball = 10_000, spot
    sim.pending = (kind, spot, team, taker)
    return sim, taker, other.keeper, taking.keeper


def _taken_at(sim, kind):
    sim.restart()
    return next(e for e in sim.events if e.restart is kind)


PENALTY_MARK = (94.0, 34.0)
THROW_SPOT = (60.0, 0.0)


@pytest.mark.parametrize(
    ("kind", "spot", "moved", "where", "at_least", "at_most"),
    [
        # everyone set: played at once
        (Restart.PENALTY, PENALTY_MARK, None, None, 10_000, 10_000),
        (Restart.THROW_IN, THROW_SPOT, None, None, 10_000, 10_000),
        # a penalty waits for its taker and for the keeper facing it, not for the other keeper
        (Restart.PENALTY, PENALTY_MARK, "taker", (54.0, 34.0), 15_000, 30_000),
        (Restart.PENALTY, PENALTY_MARK, "their keeper", (79.5, 34.0), 13_000, 30_000),
        (Restart.PENALTY, PENALTY_MARK, "own keeper", (30.0, 4.0), 10_000, 10_000),
        # any other restart waits for its taker, not for a keeper
        (Restart.THROW_IN, THROW_SPOT, "taker", (60.0, 30.0), 13_000, 30_000),
        (Restart.THROW_IN, THROW_SPOT, "their keeper", (60.0, 40.0), 10_000, 10_000),
        (Restart.THROW_IN, THROW_SPOT, "own keeper", (30.0, 4.0), 10_000, 10_000),
        # on his point means within a centimetre: 1.5 cm off, he needs one more step
        (Restart.THROW_IN, THROW_SPOT, "taker", "1.5 cm", 10_100, 10_100),
    ],
)
def test_a_restart_waits_for_its_taker_and_a_penalty_for_the_keeper_facing_it(
    monkeypatch, kind, spot, moved, where, at_least, at_most
):
    sim, taker, their_keeper, own_keeper = _all_set(monkeypatch, kind, spot)
    who = {"taker": taker, "their keeper": their_keeper, "own keeper": own_keeper}.get(moved)
    if where == "1.5 cm":
        b = sim.bodies[who]
        where = (b.x, b.y + 0.015)
    if who is not None:
        sim.bodies[who] = Body(*where)
    taken = _taken_at(sim, kind)
    assert taken.player == taker
    assert at_least <= taken.clock_ms <= at_most
    assert sim.glide is None and not sim.fixed  # play goes on: no roll, no layout held


def test_a_restart_waits_for_its_pause_to_the_step(monkeypatch):
    sim, _, _, _ = _all_set(monkeypatch, Restart.THROW_IN, THROW_SPOT, pause=7)
    assert _taken_at(sim, Restart.THROW_IN).clock_ms == 17_000


def test_a_restart_waits_for_the_ball_to_roll_to_its_spot(monkeypatch):
    # 40 m along the touchline at 8 m/s: 5 s, on the grid
    sim, _, _, _ = _all_set(monkeypatch, Restart.THROW_IN, THROW_SPOT)
    sim.ball = (20.0, 0.0)
    assert _taken_at(sim, Restart.THROW_IN).clock_ms == 15_000


@example(x=75.0, y=34.0, vx=-8.0, vy=0.0, speed=9.0)  # the review's case: he runs at the passer
@given(
    st.floats(1.0, 104.0),
    st.floats(1.0, 67.0),
    st.floats(-10.0, 10.0),
    st.floats(-10.0, 10.0),
    st.floats(9.0, 25.0),
)
@settings(max_examples=150, deadline=None)
def test_a_recipient_can_be_where_the_ball_meets_him(x, y, vx, vy, speed):
    # wherever he is and however he runs (up to his top speed): either he is on the landing when
    # the ball is, by running on, or he can get onto it and stop there in time; the ball never
    # flies faster than it was kicked
    sim = _set_up()
    passer, mate = sim.meta.home_lineup[5], sim.meta.home_lineup[8]
    sim.bodies[passer] = Body(50.0, 34.0)
    sim.take(passer)
    sim.ball = (50.0, 34.0)
    top = sim.limits[mate].top_speed
    k = min(1.0, top / max(math.hypot(vx, vy), 1e-9))
    sim.bodies[mate] = Body(x, y, vx * k, vy * k)
    who, landing, ms = sim.reachable([mate], speed)
    b = sim.bodies[mate]
    assert who == mate
    on_the_run = math.dist(landing, (b.x + b.vx * ms / 1000, b.y + b.vy * ms / 1000)) < 1e-9
    assert on_the_run or sim.in_time(mate, landing, ms), (landing, ms)
    assert math.dist(sim.ball, landing) <= speed * ms / 1000 + 1e-9


@pytest.mark.parametrize("second", [0, 1799, 1800, 1801, 2699, 2700, 2701, 3300])
def test_the_limits_are_those_of_their_second_though_worked_out_only_while_they_tire(second):
    # outside 30-45 minutes the limits cannot change, so the second is clamped to that window
    sim = _new_sim(0)
    sim.start_period(1)
    sim.t = second * 1000
    tired = sim.tired_now()
    for pid, p in sim.players.items():
        lim = Limits(p.top_speed, p.acceleration).tired(p.stamina, second)
        assert sim.limits[pid] == lim
        assert (tired[pid].top_speed, tired[pid].acceleration) == (lim.top_speed, lim.acceleration)


def test_every_taker_put_on_his_line_keeps_his_own_top_speed_in_that_step():
    # a taker waits on his aim, 0.5 m inside each line, and is put on the touchline or the flag
    # in one 100 ms step: 0.5 m, at a corner 0.71 m, after a last step onto his aim of at most
    # his acceleration's 100 ms of speed for 100 ms; a keeper is put on his goal line at a
    # penalty, 0.5 m. Every frame is judged, so the league's slowest must still keep his speed
    for p in PLAYERS.values():
        put = 0.5 if p.role == "GK" else math.hypot(0.5, 0.5)
        assert put + p.acceleration * 0.1 * 0.1 <= p.top_speed * 0.1 + MOVE_TOLERANCE, p.id


def test_a_period_starts_with_its_kick_off_at_once():
    sim = _new_sim(0)
    sim.start_period(1)
    sim.restart()
    assert sim.events[0].restart is Restart.KICK_OFF and sim.events[0].clock_ms == 0


class _Rolls:
    """A stand-in for random.Random that returns these numbers from random(), in turn."""

    def __init__(self, *rolls):
        self.rolls = list(rolls)

    def random(self):
        return self.rolls.pop(0)


@pytest.mark.parametrize(
    ("rolls", "kind", "outcome", "keeps"),
    [
        ((0.1, 0.99), EventType.PRESSURE, Outcome.RESISTED, True),
        ((0.1, 0.0), EventType.PRESSURE, Outcome.REGAIN, False),
        ((0.8, 0.99), EventType.TACKLE, Outcome.LOST, True),
        ((0.8, 0.0), EventType.TACKLE, Outcome.WON, False),
    ],
)
def test_a_challenge_has_the_ball_at_the_challengers_feet_then_at_whoever_keeps_it(
    rolls, kind, outcome, keeps
):
    sim = _set_up()
    carrier, rival = sim.meta.home_lineup[5], sim.meta.away_lineup[5]
    sim.bodies[carrier] = Body(50.0, 34.0)
    sim.bodies[rival] = Body(50.0, 35.0)
    sim.take(carrier)
    sim.ball = (50.0, 34.0)
    sim.rng = _Rolls(*rolls)
    sim.defend(rival)
    e = sim.events[-1]
    assert (e.type, e.outcome, e.player, (e.start.x, e.start.y)) == (
        kind,
        outcome,
        rival,
        (50.0, 35.0),
    )
    holder = carrier if keeps else rival
    assert sim.carrier == holder and sim.ball == sim.at(holder)
    # the challenge's frame has the ball at the challenger's feet, the next one at the holder's
    sim.tick()
    sim.snap()
    w, frames = 2 + 2 * len(sim.everyone), sim.frames[1]
    assert len(frames) == 2 * w
    assert frames[0:2].tolist() == [5000, 3500]
    at = 2 + 2 * sim.everyone.index(holder)
    assert frames[w : w + 2].tolist() == frames[w + at : w + at + 2].tolist()


def test_an_events_point_is_rounded_exactly_as_its_frame():
    # to the nearest centimetre of x * 100 (3000.6 cm is 3001), a half to the even one: 30.065 m
    # is 3006.5 cm in floats, so 30.06 m, where round(x, 2) gives 30.07; 34.015 m gives 34.02
    assert (_centi(30.006), _centi(30.065), _centi(34.015)) == (3001, 3006, 3402)
    sim = _set_up()
    carrier = sim.meta.home_lineup[5]
    sim.bodies[carrier] = Body(30.065, 34.015)
    sim.take(carrier)
    sim.ball = (30.065, 34.015)
    sim.snap()
    sim.act(EventType.RECOVERY, carrier)
    e = sim.events[-1]
    assert (e.start.x, e.start.y) == (30.06, 34.02)
    at = 2 + 2 * 5  # the carrier's x
    assert sim.frames[1][0:2].tolist() == sim.frames[1][at : at + 2].tolist() == [3006, 3402]


def test_every_step_is_a_frame_and_an_instants_last_snapshot_is_its_frame():
    sim = _set_up()
    w = 2 + 2 * len(sim.everyone)
    carrier = sim.meta.home_lineup[5]
    sim.take(carrier)
    sim.ball = sim.at(carrier)
    sim.snap()
    first = sim.everyone[0]
    sim.bodies[first] = Body(31.234, 4.005)  # put on a spot within the instant
    sim.snap()  # the instant's frame again, not a second one
    assert sim.frames[1][0:4].tolist() == [3000, 3400, 3123, 400]
    assert len(sim.frames[1]) == w
    seen = []
    for _ in range(3):
        sim.tick()
        seen.append([round(v * 100) for pid in sim.everyone for v in sim.at(pid)])
    assert len(sim.frames[1]) == 3 * w  # 0, 100 and 200 ms: 300's is kept when its step starts
    sim.snap()
    rows = [sim.frames[1][k * w : (k + 1) * w].tolist() for k in range(4)]
    assert [row[2:] for row in rows[1:]] == seen
    assert all(row[:2] == row[2 + 2 * 5 + 0 : 2 + 2 * 5 + 2] for row in rows)  # at his feet


@pytest.mark.parametrize(
    ("first_at", "first_runs", "way"),
    [
        # running at the passer: he meets the ball on the run, but cannot stop on that point
        ((70.0, 34.0), (-7.0, 0.0), "on the run"),
        # running at the touchline: the band cuts his lead short, and he stops on it in time
        ((60.0, 1.0), (0.0, -3.0), "in time"),
    ],
)
def test_a_pass_goes_to_the_first_drawn_who_can_be_there(first_at, first_runs, way):
    # the second, standing free, could take it too: the first is taken, by either way
    sim = _set_up()
    passer, first, second = (sim.meta.home_lineup[i] for i in (5, 8, 9))
    sim.bodies[passer] = Body(50.0, 34.0)
    sim.take(passer)
    sim.ball = (50.0, 34.0)
    sim.bodies[first] = Body(*first_at, *first_runs)
    sim.bodies[second] = Body(50.0, 50.0)
    landing, ms, running_on = sim.led(first, 15.0)
    assert running_on is (way == "on the run")
    assert sim.in_time(first, landing, ms) is (way == "in time")
    who, at, flight = sim.reachable([first, second], 15.0)
    assert (who, at, flight) == (first, landing, ms)


@pytest.mark.parametrize(("gap", "ms"), [(1.0, 300), (4.5, 300), (4.51, 400), (30.0, 2000)])
def test_a_standing_mate_is_met_where_he_stands_at_the_first_step_the_ball_gets_there(gap, ms):
    # at 15 m/s the ball covers 4.5 m in the shortest flight, 0.3 s, exactly; 1 m takes it too
    sim = _set_up()
    passer, mate = sim.meta.home_lineup[5], sim.meta.home_lineup[8]
    sim.bodies[passer] = Body(50.0, 34.0)
    sim.take(passer)
    sim.ball = (50.0, 34.0)
    sim.bodies[mate] = Body(50.0 + gap, 34.0)
    assert sim.led(mate, 15.0) == ((50.0 + gap, 34.0), ms, True)

import hashlib
import itertools
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
from collections import Counter
from importlib.resources import files

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from strategies import CLUBS, periods, two_clubs

from matchlens.events import (
    FRAME_MS,
    MAX_BALL_SPEED,
    PITCH_LENGTH,
    PITCH_WIDTH,
    Event,
    EventType,
    MatchMeta,
    Outcome,
    Point,
    make_event_id,
    make_frame_id,
)
from matchlens.generator import _pick_lineup, _Sim, generate_match
from matchlens.league import load_league
from matchlens.match import PLAYER_SPEED_LIMIT, Match, attacking_goal_x, validate_match

CALIBRATION_SEEDS = range(50)


@pytest.fixture(scope="module")
def matches():
    return [generate_match(seed) for seed in CALIBRATION_SEEDS]


# --- the approved generator properties ---------------------------------------------------------


@given(st.integers(0, 2**63 - 1))
@settings(max_examples=3, deadline=None)
def test_same_seed_same_output(seed):
    assert generate_match(seed) == generate_match(seed)


def test_different_seeds_differ():
    assert generate_match(1).events != generate_match(2).events


def test_same_seed_same_output_across_processes_and_hash_seeds():
    """Set iteration order must not leak into the match: two hash seeds, two processes."""
    code = (
        "import hashlib, json; from matchlens.generator import generate_match;"
        "m = generate_match(11);"
        "print(hashlib.sha256(repr((m.meta, m.events, m.snapshots)).encode()).hexdigest())"
    )
    digests = set()
    for hash_seed in ("1", "2"):
        out = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
            capture_output=True,
            text=True,
            check=True,
        )
        digests.add(out.stdout.strip())
    m = generate_match(11)
    here = hashlib.sha256(repr((m.meta, m.events, m.snapshots)).encode()).hexdigest()
    assert digests == {here}


@given(st.integers(0, 2**63 - 1))
@settings(max_examples=5, deadline=None)
def test_any_seed_gives_a_valid_match(seed):
    validate_match(generate_match(seed))  # generate_match validates too; this is the property


def test_every_calibration_match_validates(matches):
    for m in matches:
        validate_match(m)


def test_time_is_monotonic_and_ids_are_unique_and_contiguous(matches):
    for m in matches:
        times = [(e.period, e.clock_ms) for e in m.events]
        assert times == sorted(times)
        assert [e.event_id for e in m.events] == [
            make_event_id(m.meta.match_id, i) for i in range(len(m.events))
        ]


def test_every_loose_ball_ends_in_a_recovery_or_at_an_opponent(matches):
    """A ball that lands loose is recovered where it lies after a run of at least 0.5 s; one that
    lands at an opponent is intercepted or, after a block, cleared by the blocker."""
    failed = (Outcome.INCOMPLETE, Outcome.BLOCKED, Outcome.WOODWORK)
    recoveries = 0
    for m in matches:
        for prev, e in itertools.pairwise(m.events):
            loose = prev.end is not None and prev.outcome in failed
            if e.type is EventType.RECOVERY:
                recoveries += 1
                assert loose and e.start == prev.end
                assert e.clock_ms >= prev.clock_ms + prev.duration_ms + 500
                if prev.outcome is Outcome.BLOCKED:  # the blocker's side clears instead
                    assert e.team == prev.team
            elif loose:
                assert e.type in (EventType.INTERCEPTION, EventType.CLEARANCE)
                assert e.team != prev.team and e.start == prev.end
                assert e.clock_ms == prev.clock_ms + prev.duration_ms
    assert recoveries > 0


def test_coordinates_are_on_the_pitch(matches):
    for m in matches:
        for s in m.snapshots:
            for _, x, y in s.players:
                assert 0 <= x <= PITCH_LENGTH and 0 <= y <= PITCH_WIDTH
            assert 0 <= s.ball[0] <= PITCH_LENGTH and 0 <= s.ball[1] <= PITCH_WIDTH


def test_score_equals_goal_events(matches):
    for m in matches:
        scoring_shots = [
            e for e in m.events if e.type is EventType.SHOT and e.outcome is Outcome.GOAL
        ]
        goals = [e for e in m.events if e.type is EventType.GOAL]
        assert len(goals) == len(scoring_shots)
        home, away = m.score()
        assert home == sum(e.team == m.meta.home for e in goals)
        assert away == sum(e.team == m.meta.away for e in goals)


def test_both_periods_end_in_stoppage_time(matches):
    for m in matches:
        ends = [e for e in m.events if e.type is EventType.PERIOD_END]
        assert [e.period for e in ends] == [1, 2]
        for e in ends:
            assert 45 * 60_000 <= e.clock_ms <= 52 * 60_000


def test_tracking_is_exactly_10_hz_with_speeds_under_the_limits():
    m = generate_match(0)
    frames = list(m.frames())  # about 57 000 frames, 5 s (PROGRESS.md metrics)
    for period in (1, 2):
        in_period = [f for f in frames if f.period == period]
        assert [f.clock_ms for f in in_period] == list(
            range(0, len(in_period) * FRAME_MS, FRAME_MS)
        )
        last_event = max(e.clock_ms for e in m.events if e.period == period)
        assert in_period[-1].clock_ms >= last_event - FRAME_MS  # frames sit on the 100 ms grid
        for before, after in zip(in_period, in_period[1:], strict=False):
            assert after.frame_id == make_frame_id(m.meta.match_id, period, after.clock_ms)
            assert len(after.players) == 22
            for a, b in zip(before.players, after.players, strict=True):
                assert a.player == b.player
                assert math.hypot(b.x - a.x, b.y - a.y) / 0.1 <= PLAYER_SPEED_LIMIT + 0.2
            ball = math.hypot(after.ball.x - before.ball.x, after.ball.y - before.ball.y) / 0.1
            assert ball <= MAX_BALL_SPEED + 0.2
    by_time = {(f.period, f.clock_ms): f for f in frames}
    for e in m.events:
        if e.team is not None and e.clock_ms % FRAME_MS == 0:
            f = by_time[(e.period, e.clock_ms)]
            assert math.hypot(f.ball.x - e.start.x, f.ball.y - e.start.y) <= 0.02


def test_calibration_over_50_seeds(matches):
    """Match-level numbers in football-realistic ranges (means over the seeds)."""
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


# --- fixtures and lineups ----------------------------------------------------------------------


@given(two_clubs, st.integers(0, 1000))
@settings(max_examples=5, deadline=None)
def test_clubs_can_be_chosen(clubs, seed):
    home, away = clubs
    m = generate_match(seed, home=home, away=away)
    assert (m.meta.home, m.meta.away) == (home, away)
    assert m.meta.seed == seed and m.meta.match_id == f"m{seed}{home}{away}"


@pytest.mark.parametrize("seed", range(8))
def test_one_club_can_be_chosen_and_the_other_differs(seed):
    assert generate_match(seed).meta.match_id == f"m{seed}"
    for kw in ({"home": "cor"}, {"away": "cor"}):
        m = generate_match(seed, **kw)
        assert m.meta.home != m.meta.away
        side, club = next(iter(kw.items()))
        assert getattr(m.meta, side) == club
        assert m.meta.match_id == f"m{seed}{m.meta.home}{m.meta.away}"


def test_lineups_are_eleven_from_the_squad_with_one_keeper(matches):
    from matchlens.league import load_league

    squads = {c.id: {p.id: p.position for p in c.players} for c in load_league().clubs}
    for m in matches:
        for team, lineup in ((m.meta.home, m.meta.home_lineup), (m.meta.away, m.meta.away_lineup)):
            positions = Counter(squads[team][p] for p in lineup)
            assert positions == {"GK": 1, "DF": 4, "MF": 3, "FW": 3}


@given(st.integers(0, 4), st.integers(0, 4))
def test_score_counts_goal_events_per_team(home_goals, away_goals):
    lineup = {t: tuple(f"{t}-p{i:02d}" for i in range(1, 12)) for t in ("cor", "vel")}
    meta = MatchMeta("m1", "cor", "vel", lineup["cor"], lineup["vel"], 1)
    events, seq = [], 0
    for team, n in (("cor", home_goals), ("vel", away_goals)):
        for _ in range(n):
            goal_x = attacking_goal_x(meta, team, 1)
            shot = Event(make_event_id("m1", seq), 1, seq * 1000, EventType.SHOT, team,
                         f"{team}-p09", Point(goal_x - 10 if goal_x else 10, 34), Point(goal_x, 34),
                         Outcome.GOAL, None, 500)  # fmt: skip
            goal = Event(make_event_id("m1", seq + 1), 1, seq * 1000 + 500, EventType.GOAL, team,
                         f"{team}-p09", Point(goal_x, 34), related=shot.event_id)  # fmt: skip
            events += [shot, goal]
            seq += 2
    assert Match(meta, tuple(events), ()).score() == (home_goals, away_goals)


def test_unknown_club_is_refused():
    with pytest.raises(ValueError, match="unknown club: 'xyz'"):
        generate_match(1, home="xyz")
    with pytest.raises(ValueError, match=re.escape("unknown club: ['cor']")):
        generate_match(1, away=["cor"])
    with pytest.raises(ValueError, match="home and away are both cor"):
        generate_match(1, home="cor", away="cor")


# generator v1 as submitted (`m7-submission`, the live app's demo matches): M9 builds v2 beside it
# and must not change a v1 match, not even through the league data both read
V1_DIGESTS = {
    0: "1037b0bad2d4df48aabccbbb2554c3d8fa0fb94d32e251d1767962c87676efd8",
    1: "d02d3ccc2695ee708f2e76a006f9de73ec843f79d443a0d83598764c91af0da2",
    3: "b24738d181caefee1dbe7361b6188fa9d6113735394933c25ffdc236603ec64e",
}


@pytest.mark.parametrize("seed", sorted(V1_DIGESTS))
def test_v1_matches_stay_as_submitted(seed):
    m = generate_match(seed)
    digest = hashlib.sha256(repr((m.meta, m.events, m.snapshots)).encode()).hexdigest()
    assert digest == V1_DIGESTS[seed]


def test_v1s_view_of_the_league_stays_as_submitted():
    # the demo seeds draw three of the four clubs; v1 reads each player's id, name, number and
    # position, so these must not change in any club (digest computed before M9 item 2)
    rows = sorted(
        (p.id, p.name, p.number, p.position) for c in load_league().clubs for p in c.players
    )
    digest = hashlib.sha256(repr(rows).encode()).hexdigest()
    assert digest == "41c4c4369485497cc010db46ce8d04b1f1b396ff971c0ea4627773c6ac604e2a"


def test_short_squad_is_refused():
    from matchlens.league import load_league, parse_league

    raw = json.loads(files("matchlens").joinpath("data/league.json").read_text(encoding="utf-8"))
    cor = next(c for c in raw["clubs"] if c["id"] == "cor")
    for p in [p for p in cor["players"] if p["position"] == "DF"][:3]:
        p["position"] = "MF"
    league = parse_league(raw)
    assert load_league() != league
    with pytest.raises(ValueError, match="cor: 3 DF, the formation needs 4"):
        generate_match(1, home="cor", league=league)


class _Scripted:
    """A stand-in for random.Random that never scores and always chooses a save."""

    def random(self):
        return 0.99

    def choices(self, population, weights=None):
        return [population[0]]

    def uniform(self, a, b):
        return (a + b) / 2

    def choice(self, seq):
        return seq[0]

    def randint(self, a, b):
        return a


@pytest.mark.parametrize(("keeper_x", "expected"), [(1.5, EventType.SAVE), (40.0, EventType.GOAL)])
def test_keeper_who_cannot_reach_the_save_concedes(keeper_x, expected):
    """A shot the keeper could only save by teleporting becomes a goal (KEEPER_REACH)."""
    m = generate_match(0)
    rng = random.Random(0)  # replay generate_match's draws so the slots match m.meta's lineups
    clubs = {c.id: c for c in load_league().clubs}
    rng.sample(sorted(clubs), 2)
    slots = {}
    for team in (m.meta.home, m.meta.away):
        lineup, team_slots = _pick_lineup(rng, clubs[team])
        assert lineup == (m.meta.home_lineup if team == m.meta.home else m.meta.away_lineup)
        slots.update(team_slots)
    sim = _Sim(rng=rng, meta=m.meta, slots=slots)
    sim.start_period(1)
    sim.take_restart()  # kick-off, so the state is consistent
    striker = next(p for p in m.meta.home_lineup if sim.group(p) == "FW")
    keeper = next(p for p in m.meta.away_lineup if sim.group(p) == "GK")
    sim.holder, sim.ball = striker, (97.0, 34.0)  # home attacks x = 105 in period 1
    sim.pos[striker], sim.pos[keeper] = sim.ball, (105.0 - keeper_x, 34.0)
    sim.rng = _Scripted()
    sim.shoot()
    assert sim.events[-1].type is expected
    assert sim.events[-2].type is EventType.SHOT


@given(two_clubs, periods)
def test_attacking_directions_are_opposite_and_swap_at_half_time(clubs, period):
    home, away = clubs
    lineup = tuple(f"{home}-p{i:02d}" for i in range(1, 12))
    meta = MatchMeta("m1", home, away, lineup, tuple(f"{away}-p{i:02d}" for i in range(1, 12)), 1)
    assert (
        attacking_goal_x(meta, home, period) + attacking_goal_x(meta, away, period) == PITCH_LENGTH
    )
    assert attacking_goal_x(meta, home, 1) != attacking_goal_x(meta, home, 2)
    assert attacking_goal_x(meta, home, 1) == PITCH_LENGTH
    with pytest.raises(ValueError, match="is not playing"):
        attacking_goal_x(meta, next(c for c in CLUBS if c not in clubs), period)

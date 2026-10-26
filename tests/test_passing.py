import dataclasses
import functools
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from strategies import CLUBS, lineup, match_metas

from matchlens.events import (
    MAX_PERIOD_MS,
    MAX_TRAVEL_MS,
    PERIODS,
    PITCH_LENGTH,
    PITCH_WIDTH,
    Event,
    EventType,
    MatchMeta,
    Outcome,
    Point,
    Restart,
    make_event_id,
)
from matchlens.generator import generate_match
from matchlens.match import Snapshot
from matchlens.stats.passing import (
    PassRating,
    PassStats,
    Zone,
    pass_difficulty,
    pass_ratings,
    pass_stats,
)

H, A = CLUBS[:2]
META = MatchMeta("m1", H, A, lineup(H), lineup(A), 1)  # H attacks x = 105 in period 1


def a_pass(team, start, end, outcome=Outcome.COMPLETE, restart=None, period=1, clock=1_000):
    recipient = f"{team}-p10" if outcome is Outcome.COMPLETE else None
    return Event(
        make_event_id("m1", 0), period, clock, EventType.PASS, team, f"{team}-p09", Point(*start),
        end=Point(*end), duration_ms=2_000, outcome=outcome, restart=restart, recipient=recipient,
    )  # fmt: skip


def tracking(opponent_of: str, at: tuple[float, float], period=1) -> list[Snapshot]:
    """Everyone at a corner flag except one opponent of `opponent_of`, who stands `at`, at the
    instant a pass of `a_pass` arrives."""
    players = [(p, 0.0, 0.0) for p in META.home_lineup + META.away_lineup]
    i = next(n for n, (p, _, _) in enumerate(players) if not p.startswith(opponent_of))
    players[i] = (players[i][0], *at)
    return [Snapshot(period, 3_000, at, tuple(players))]


def rate(e: Event, snapshots: list[Snapshot]) -> PassRating:
    (rating,) = pass_ratings(META, [e], snapshots)
    return rating


# --- examples ----------------------------------------------------------------------------------


def test_a_forward_pass_into_the_final_third():
    r = rate(a_pass(H, (40, 34), (70, 34)), tracking(H, (70, 39)))
    # 30 m of 60 -> 20; opponent 5 m of 10 -> 15; straight forward -> 15; final third 2/3 -> 10
    assert (r.length_m, r.forward, r.opponent_m, r.zone) == (30.0, 1.0, 5.0, Zone.FINAL_THIRD)
    assert r.difficulty == 60
    assert r.complete and r.progressive  # own half to the opponent's, 30 m closer (15 needed)


def test_the_same_pass_by_the_team_attacking_the_other_way():
    r = rate(a_pass(A, (65, 34), (35, 34)), tracking(A, (35, 29)))
    assert (r.length_m, r.forward, r.opponent_m, r.zone) == (30.0, 1.0, 5.0, Zone.FINAL_THIRD)
    assert (r.difficulty, r.progressive) == (60, True)


def test_the_home_team_attacks_the_other_way_after_half_time():
    r = rate(a_pass(H, (65, 34), (35, 34), period=2), tracking(H, (35, 29), period=2))
    assert (r.length_m, r.forward, r.opponent_m, r.zone) == (30.0, 1.0, 5.0, Zone.FINAL_THIRD)
    assert (r.difficulty, r.progressive) == (60, True)


def test_a_square_pass_of_no_length():
    r = rate(a_pass(H, (30, 34), (30, 34)), tracking(H, (30, 41.5)))
    assert (r.length_m, r.forward, r.zone) == (0.0, 0.0, Zone.OWN_THIRD)
    assert r.difficulty == 0 + 30 * 2.5 / 10 + 15 / 2 + 0  # 15


@pytest.mark.parametrize(
    ("end", "zone"),
    [
        ((34.99, 34), Zone.OWN_THIRD),
        ((35, 34), Zone.MIDDLE_THIRD),
        ((69.99, 34), Zone.MIDDLE_THIRD),
        ((70, 34), Zone.FINAL_THIRD),
        ((88.49, 34), Zone.FINAL_THIRD),
        ((88.5, 34), Zone.PENALTY_AREA),
        ((88.5, 13.84), Zone.PENALTY_AREA),
        ((88.5, 13.83), Zone.FINAL_THIRD),
        ((105, 54.16), Zone.PENALTY_AREA),
        ((105, 54.17), Zone.FINAL_THIRD),
    ],
)
def test_zone_edges(end, zone):
    assert rate(a_pass(H, (60, 34), end), tracking(H, (0, 0))).zone is zone


def test_a_back_pass_with_nobody_near():
    r = rate(a_pass(H, (60, 34), (45, 34)), tracking(H, (100, 60)))
    assert (r.forward, r.zone, r.progressive) == (-1.0, Zone.MIDDLE_THIRD, False)
    assert r.difficulty == round(40 * 15 / 60 + 0 + 0 + 15 / 3)  # 15


def test_a_pass_into_the_penalty_area():
    r = rate(a_pass(H, (80, 50), (95, 30)), tracking(H, (95, 30)))  # marked tightly
    assert r.zone is Zone.PENALTY_AREA and r.opponent_m == 0.0
    # 25 m long, forward 15/25 = 0.6: 40*25/60 + 30 + 15*0.8 + 15
    assert r.difficulty == round(40 * 25 / 60 + 30 + 15 * 0.8 + 15)  # 74


def test_a_failed_pass_has_no_receiver_to_rate():
    r = rate(a_pass(H, (40, 34), (70, 34), Outcome.INCOMPLETE), [])  # no tracking needed
    assert (r.complete, r.opponent_m, r.difficulty, r.progressive) == (False, None, None, False)
    assert (r.length_m, r.zone) == (30.0, Zone.FINAL_THIRD)


def test_progressive_needs_a_complete_open_play_pass():
    long_ball = ((20, 34), (60, 34))  # 40 m closer, own half to the opponent's
    snaps = tracking(H, (0, 0))
    assert rate(a_pass(H, *long_ball), snaps).progressive
    assert not rate(a_pass(H, *long_ball, outcome=Outcome.INCOMPLETE), snaps).progressive
    assert not rate(a_pass(H, *long_ball, restart=Restart.FREE_KICK), snaps).progressive
    # within the own half 30 m are needed, within the opponent's 10 m
    assert not rate(a_pass(H, (5, 34), (30, 34)), snaps).progressive
    assert rate(a_pass(H, (5, 34), (35, 34)), snaps).progressive
    assert rate(a_pass(H, (70, 34), (80, 34)), snaps).progressive
    assert not rate(a_pass(H, (70, 34), (79, 34)), snaps).progressive
    # the halfway line belongs to the opponent's half: 10 m are enough from there, 15 from behind
    assert rate(a_pass(H, (52.5, 34), (62.5, 34)), snaps).progressive
    assert not rate(a_pass(H, (52.49, 34), (62.49, 34)), snaps).progressive
    # ... also where the pass ends: onto the line 15 m are enough, 1 cm short of it 30 are needed
    assert rate(a_pass(H, (37.5, 34), (52.5, 34)), snaps).progressive
    assert not rate(a_pass(H, (37.49, 34), (52.49, 34)), snaps).progressive
    # each threshold exactly, and 1 cm short of it
    assert not rate(a_pass(H, (5, 34), (34.99, 34)), snaps).progressive  # 30 m in the own half
    assert not rate(a_pass(H, (37.51, 34), (52.5, 34)), snaps).progressive  # 15 m across
    assert not rate(a_pass(H, (70, 34), (79.99, 34)), snaps).progressive  # 10 m in theirs
    # closer to the centre of the goal, not to its line: 12 m up the touchline gain only 8 m
    assert not rate(a_pass(H, (70, 2), (82, 2)), snaps).progressive


def test_no_tracking_where_the_ball_arrives():
    with pytest.raises(ValueError, match="no tracking"):
        pass_ratings(META, [a_pass(H, (40, 34), (70, 34), clock=900)], tracking(H, (0, 0)))


def test_the_nearest_opponent_not_the_nearest_player():
    players = [(p, 0.0, 0.0) for p in META.home_lineup + META.away_lineup]
    players[9] = (f"{H}-p10", 70.0, 34.0)  # the receiver, where the ball arrives
    players[10] = (players[10][0], 70.0, 35.0)  # a team-mate 1 m away
    players[11] = (players[11][0], 70.0, 42.0)  # the first opponent: 8 m away
    players[12] = (players[12][0], 70.0, 31.0)  # the next one is nearer: 3 m away
    snaps = [Snapshot(1, 3_000, (70.0, 34.0), tuple(players))]
    assert rate(a_pass(H, (40, 34), (70, 34)), snaps).opponent_m == 3.0


def test_live_tracking_must_reach_the_arrival():
    """Cut at the clock of a pass in flight, tracking lacks its arrival; whole tracking rates it
    and `arrival_ms` tells the caller it has not arrived yet."""
    m, ratings = real(7)
    r = next(r for r in ratings if r.complete and r.period == 2)  # clocks restart at half-time
    k = next(i for i, e in enumerate(m.events) if e.event_id == r.event_id) + 1
    cut = [s for s in m.snapshots if (s.period, s.clock_ms) <= (r.period, r.clock_ms)]
    with pytest.raises(ValueError, match="no tracking"):
        pass_ratings(m.meta, m.events[:k], cut)
    live = pass_ratings(m.meta, m.events[:k], m.snapshots)
    assert live[-1] == r and r.arrival_ms > r.clock_ms
    now = (r.period, r.clock_ms)
    assert [x for x in live if (x.period, x.arrival_ms) <= now] == live[:-1]


def test_stats_without_passes():
    assert pass_stats([]) == PassStats(0, 0, 0, None, None, None, (), (), ())


def test_stats_of_a_player_and_a_team():
    snaps = tracking(H, (0, 0))
    ratings = [
        dataclasses.replace(rate(a_pass(H, (40, 34), (70, 34)), snaps), event_id="m1-e00001"),
        dataclasses.replace(
            rate(a_pass(H, (60, 34), (45, 34), Outcome.INCOMPLETE), snaps),
            event_id="m1-e00002",
            player=f"{H}-p05",
        ),
    ]
    team = pass_stats(ratings, team=H)
    assert (team.passes, team.completed, team.progressive, team.completion) == (2, 1, 1, 0.5)
    assert team.average_length_m == 22.5
    assert team.average_completed_difficulty == 45  # the completed pass only: 20 + 0 + 15 + 10
    assert team.event_ids == ("m1-e00001", "m1-e00002")
    assert team.completed_ids == team.progressive_ids == ("m1-e00001",)
    assert pass_stats(ratings, player=f"{H}-p05").event_ids == ("m1-e00002",)
    assert pass_stats(ratings, team=A).passes == 0


# --- the difficulty rating ---------------------------------------------------------------------

lengths = st.floats(0, 120, allow_nan=False)
forwards = st.floats(-1, 1, allow_nan=False)
gaps = st.floats(0, 120, allow_nan=False)
zones = st.sampled_from(Zone)


@given(lengths, forwards, gaps, zones)
def test_difficulty_is_0_to_100(length, forward, gap, zone):
    assert 0 <= pass_difficulty(length, forward, gap, zone) <= 100


@given(lengths, lengths, forwards, gaps, zones)
def test_difficulty_never_falls_with_length(a, b, forward, gap, zone):
    short, long = sorted((a, b))
    assert pass_difficulty(short, forward, gap, zone) <= pass_difficulty(long, forward, gap, zone)


@given(lengths, forwards, forwards, gaps, gaps, zones, zones)
def test_difficulty_never_falls_as_the_rest_gets_harder(length, f1, f2, g1, g2, z1, z2):
    back, ahead = sorted((f1, f2))
    near, far = sorted((g1, g2))
    easy, hard = sorted((z1, z2))
    assert pass_difficulty(length, back, near, easy) <= pass_difficulty(length, ahead, near, easy)
    assert pass_difficulty(length, back, far, easy) <= pass_difficulty(length, back, near, easy)
    assert pass_difficulty(length, back, near, easy) <= pass_difficulty(length, back, near, hard)


@pytest.mark.parametrize(
    "args",
    [
        (-0.1, 0, 5, Zone.OWN_THIRD),
        (10, 1.01, 5, Zone.OWN_THIRD),
        (10, 0, math.nan, 0),
        (60, 1, 0, 7),  # no such zone
    ],
)
def test_difficulty_rejects_impossible_passes(args):
    with pytest.raises(ValueError):
        pass_difficulty(*args)


@st.composite
def rating_lists(draw) -> list[PassRating]:
    """Ratings as `pass_ratings` makes them: only a complete pass has a difficulty and an
    opponent distance, and only a complete pass can be progressive."""
    ratings = []
    for n in range(draw(st.integers(0, 30))):
        team = draw(st.sampled_from((H, A)))
        complete = draw(st.booleans())
        ratings.append(
            PassRating(
                event_id=make_event_id("m1", n),
                period=1,
                clock_ms=1_000 * n,
                arrival_ms=1_000 * n + 500,
                team=team,
                player=f"{team}-p{draw(st.integers(1, 3)):02d}",
                complete=complete,
                length_m=draw(lengths),
                forward=draw(forwards),
                opponent_m=draw(gaps) if complete else None,
                zone=draw(zones),
                progressive=complete and draw(st.booleans()),
                difficulty=draw(st.integers(0, 100)) if complete else None,
            )
        )
    return ratings


@given(rating_lists())
def test_stats_are_consistent_and_add_up(ratings):
    everyone = pass_stats(ratings)
    teams = [pass_stats(ratings, team=t) for t in (H, A)]
    players = [pass_stats(ratings, player=f"{t}-p{n:02d}") for t in (H, A) for n in (1, 2, 3)]
    assert everyone.event_ids == tuple(r.event_id for r in ratings)
    for field in ("passes", "completed", "progressive"):
        assert getattr(everyone, field) == sum(getattr(s, field) for s in teams)
        assert getattr(everyone, field) == sum(getattr(s, field) for s in players)
    for s in [everyone, *teams, *players]:
        assert 0 <= s.progressive <= s.completed <= s.passes
        assert (s.completion is None) == (s.passes == 0)
        assert s.completion is None or 0 <= s.completion <= 1
        assert (s.average_completed_difficulty is None) == (s.completed == 0)
        average = s.average_completed_difficulty
        assert average is None or 0 <= average <= 100
        # each value's own events: every pass, the completed ones, the progressive ones
        assert len(s.event_ids) == s.passes and len(s.completed_ids) == s.completed
        assert len(s.progressive_ids) == s.progressive
        assert set(s.progressive_ids) <= set(s.completed_ids) <= set(s.event_ids)
        by_id = {r.event_id: r for r in ratings}
        assert s.completed_ids == tuple(i for i in s.event_ids if by_id[i].complete)
        assert s.progressive_ids == tuple(i for i in s.event_ids if by_id[i].progressive)


# --- mirror: the pitch turned round and the teams' ends swapped ---------------------------------


def mirror_xy(x: float, y: float) -> tuple[float, float]:
    return round(PITCH_LENGTH - x, 2), round(PITCH_WIDTH - y, 2)


def mirror_event(e: Event) -> Event:
    def point(p: Point | None) -> Point | None:
        return p and Point(*mirror_xy(p.x, p.y))

    return dataclasses.replace(e, start=point(e.start), end=point(e.end))


def mirror_snapshot(s: Snapshot) -> Snapshot:
    players = tuple((p, *mirror_xy(x, y)) for p, x, y in s.players)
    return Snapshot(s.period, s.clock_ms, mirror_xy(*s.ball), players)


def mirror_meta(m: MatchMeta) -> MatchMeta:
    return MatchMeta(m.match_id, m.away, m.home, m.away_lineup, m.home_lineup, m.seed)


cm = st.integers(0, round(PITCH_LENGTH * 100)).map(lambda v: v / 100)
cm_y = st.integers(0, round(PITCH_WIDTH * 100)).map(lambda v: v / 100)


@st.composite
def rated_passes(draw):
    """A match, one pass of either team with coordinates to the centimetre, and the snapshot
    at the instant it arrives."""
    meta = draw(match_metas())
    team = draw(st.sampled_from((meta.home, meta.away)))
    outcome = draw(st.sampled_from([Outcome.COMPLETE, Outcome.INCOMPLETE, Outcome.OUT]))
    start, end = Point(draw(cm), draw(cm_y)), Point(draw(cm), draw(cm_y))
    e = Event(
        make_event_id(meta.match_id, 0), draw(st.sampled_from(PERIODS)),
        draw(st.integers(0, MAX_PERIOD_MS - MAX_TRAVEL_MS)), EventType.PASS, team,
        f"{team}-p09", start, end=end, duration_ms=MAX_TRAVEL_MS, outcome=outcome,
        restart=draw(st.none() | st.sampled_from(Restart)),
        recipient=f"{team}-p10" if outcome is Outcome.COMPLETE else None,
    )  # fmt: skip
    players = tuple((p, draw(cm), draw(cm_y)) for p in meta.home_lineup + meta.away_lineup)
    arrival = Snapshot(e.period, e.clock_ms + e.duration_ms, (end.x, end.y), players)
    return meta, e, [arrival]


@given(rated_passes())
def test_mirroring_keeps_a_rating(case):
    meta, e, snaps = case
    mirrored = pass_ratings(mirror_meta(meta), [mirror_event(e)], [mirror_snapshot(snaps[0])])
    assert mirrored == pass_ratings(meta, [e], snaps)
    # the ends swap at half-time: the same pass in the other period, on the pitch turned round
    other = 3 - e.period
    swapped = dataclasses.replace(mirror_snapshot(snaps[0]), period=other)
    after_the_break = dataclasses.replace(mirror_event(e), period=other)
    (later,) = pass_ratings(meta, [after_the_break], [swapped])
    assert [dataclasses.replace(later, period=e.period)] == pass_ratings(meta, [e], snaps)


# --- real matches ------------------------------------------------------------------------------

REAL_SEEDS = (3, 7)


@functools.cache
def real(seed: int):
    m = generate_match(seed)
    return m, pass_ratings(m.meta, m.events, m.snapshots)


@pytest.mark.parametrize("seed", REAL_SEEDS)
def test_real_match_mirrored_rates_the_same(seed):
    m, ratings = real(seed)
    mirrored = pass_ratings(
        mirror_meta(m.meta),
        [mirror_event(e) for e in m.events],
        [mirror_snapshot(s) for s in m.snapshots],
    )
    assert mirrored == ratings


@pytest.mark.parametrize("seed", REAL_SEEDS)
def test_real_match_counts_add_up(seed):
    m, ratings = real(seed)
    assert [r.event_id for r in ratings] == [
        e.event_id for e in m.events if e.type is EventType.PASS
    ]
    everyone = pass_stats(ratings)
    teams = [pass_stats(ratings, team=t) for t in (m.meta.home, m.meta.away)]
    assert everyone.passes == sum(t.passes for t in teams)
    for team, lineup_ in ((m.meta.home, m.meta.home_lineup), (m.meta.away, m.meta.away_lineup)):
        whole = pass_stats(ratings, team=team)
        players = [pass_stats(ratings, team=team, player=p) for p in lineup_]
        for r in ratings:
            assert (r.difficulty is None) == (r.opponent_m is None) == (not r.complete)
        for s in [whole, *players]:
            assert 0 <= s.progressive <= s.completed <= s.passes
            assert s.completion is None or 0 <= s.completion <= 1
            average = s.average_completed_difficulty
            assert average is None or 0 <= average <= 100
        assert whole.passes == sum(p.passes for p in players)
        assert whole.completed == sum(p.completed for p in players)
        assert whole.progressive == sum(p.progressive for p in players)
        assert sorted(whole.event_ids) == sorted(i for p in players for i in p.event_ids)
        length = math.fsum(p.average_length_m * p.passes for p in players if p.passes)
        assert math.isclose(whole.average_length_m * whole.passes, length, rel_tol=1e-12)


@settings(deadline=None)  # the first example generates the match
@given(st.sampled_from(REAL_SEEDS), st.data())
def test_real_match_prefix_rates_its_passes(seed, data):
    m, ratings = real(seed)
    k = data.draw(st.integers(0, len(m.events)))
    passes = sum(e.type is EventType.PASS for e in m.events[:k])
    assert pass_ratings(m.meta, m.events[:k], m.snapshots) == ratings[:passes]

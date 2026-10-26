import dataclasses
import json
import math
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import pytest
import real
from hypothesis import given, settings
from hypothesis import strategies as st
from strategies import frame_clocks, match_ids, match_metas, periods

from matchlens.events import (
    FRAMES_PER_PERIOD,
    MAX_PERIOD_MS,
    PERIODS,
    PITCH_LENGTH,
    PITCH_WIDTH,
    EventType,
    display_clock,
    frame_time,
    make_frame_id,
)
from matchlens.facts import (
    WINDOW_MS,
    _percent,
    display_minute,
    facts_at,
    match_facts,
    player_facts,
)
from matchlens.generator import generate_match
from matchlens.league import load_league
from matchlens.match import Match, Snapshot
from matchlens.stats.flow import control, momentum, pressing
from matchlens.stats.passing import pass_ratings, pass_stats
from matchlens.stats.possession import possession, spells
from matchlens.stats.readings import VOCABULARY
from matchlens.stats.speed import HARD_SHOT_MS, ball_speeds


def match7() -> Match:
    return real.match(7)


def facts7():
    return real.facts(7)


def half_up(value: float, places: int) -> str:
    return str(Decimal(repr(value)).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP))


# --- frames by id and by time -------------------------------------------------------------------


@given(match_ids, periods, frame_clocks)
def test_frame_time_inverts_make_frame_id(match_id, period, clock_ms):
    assert frame_time(make_frame_id(match_id, period, clock_ms)) == (match_id, period, clock_ms)


@pytest.mark.parametrize("bad", ["m7-e00001", f"m7-f{2 * FRAMES_PER_PERIOD:06d}", "m7-f12"])
def test_frame_time_rejects_what_is_no_frame_id(bad):
    with pytest.raises(ValueError):
        frame_time(bad)


cm = st.integers(0, round(PITCH_LENGTH * 100)).map(lambda v: v / 100)
cm_y = st.integers(0, round(PITCH_WIDTH * 100)).map(lambda v: v / 100)


@st.composite
def tracked_matches(draw) -> Match:
    """Tracking only: a few snapshots per period at any clocks, everyone anywhere."""
    meta = draw(match_metas())
    players = meta.home_lineup + meta.away_lineup
    snaps = []
    for period in PERIODS:
        for clock in sorted({0, *draw(st.lists(st.integers(1, 3_000), max_size=5))}):
            positions = tuple((p, draw(cm), draw(cm_y)) for p in players)
            snaps.append(Snapshot(period, clock, (draw(cm), draw(cm_y)), positions))
    return Match(meta, (), tuple(snaps))


@given(tracked_matches())
def test_frame_at_is_the_frame_that_frames_yields(m):
    frames = list(m.frames())
    assert [m.frame_at(f.period, f.clock_ms) for f in frames] == frames


@pytest.mark.parametrize(("period", "clock_ms"), [(1, 50), (1, -100), (2, MAX_PERIOD_MS), (3, 0)])
def test_frame_at_has_no_frame_off_the_grid_or_after_the_period(period, clock_ms):
    with pytest.raises(ValueError):
        match7().frame_at(period, clock_ms)


# --- the display minute -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "clock_ms", "minute"),
    [
        (1, 0, "1'"),
        (1, 59_999, "1'"),
        (1, 60_000, "2'"),
        (1, 2_699_999, "45'"),
        (1, 2_700_000, "45+1'"),
        (1, 2_833_000, "45+3'"),  # 45+2:13
        (2, 1_343_000, "68'"),  # 67:23
        (2, 2_760_000, "90+2'"),  # 90+1:00
    ],
)
def test_display_minute_counts_upwards(period, clock_ms, minute):
    assert display_minute(period, clock_ms) == minute


@given(periods, st.integers(0, MAX_PERIOD_MS))
def test_display_minute_is_the_clock_s_minute_plus_one(period, clock_ms):
    minutes = display_clock(period, clock_ms).split(":")[0]
    base, _, extra = minutes.partition("+")
    expected = f"{base}+{int(extra) + 1}'" if extra else f"{int(base) + 1}'"
    assert display_minute(period, clock_ms) == expected


# --- the facts of a match -----------------------------------------------------------------------


def assert_evidence_inside(facts, m: Match) -> None:
    """Every event and frame id exists in the match and lies inside its fact's time range."""
    events = {e.event_id: e for e in m.events}
    for f in facts:
        assert f.match_id == m.meta.match_id and f.start <= f.end
        assert f.source in ("engine", "league", "clock") and f.display
        for i in f.event_ids:
            assert f.start <= (events[i].period, events[i].clock_ms) <= f.end
        for i in f.frame_ids:
            match_id, period, clock_ms = frame_time(i)
            assert match_id == m.meta.match_id and f.start <= (period, clock_ms) <= f.end
            assert m.frame_at(period, clock_ms).frame_id == i
    ids = [f.fact_id for f in facts]
    assert len(ids) == len(set(ids))


def test_match_facts_cite_evidence_inside_their_ranges():
    assert_evidence_inside(facts7(), match7())


def test_match_facts_cover_every_stat():
    names = {f.name for f in facts7()}
    assert names == {
        "score", "goals", "possession", "passes", "passes_completed", "pass_completion",
        "average_pass_length", "progressive_passes", "pass_difficulty", "distance",
        "top_speed", "shot_speed", "shirt_number", "pressing_actions", "pressing_per_minute",
        "momentum", "possession_changes", "possession_changes_per_minute",
        "average_possession_length", "chaos", "score_reading", "goal_reading",
        "possession_reading", "momentum_reading", "chaos_reading",
    }  # fmt: skip
    by_scope = {}
    for f in facts7():
        if f.name == "possession":
            by_scope.setdefault(f.fact_id.split("/")[2], []).append(int(f.display[:-1]))
    assert set(by_scope) == {"match", "p1", "p2"}
    assert all(sum(shares) == 100 for shares in by_scope.values())
    goals = {f.team: f.display for f in facts7() if f.name == "goals"}
    (score,) = [f for f in facts7() if f.name == "score"]
    m = match7()
    assert score.display == f"{goals[m.meta.home]}–{goals[m.meta.away]}" == "3–2"


def test_match_facts_are_json_and_deterministic_per_seed():
    dicts = [f.to_dict() for f in facts7()]
    assert json.loads(json.dumps(dicts)) == dicts
    assert match_facts(generate_match(7)) == facts7()  # a fresh match from the same seed


def test_player_facts_are_the_players_own():
    got = player_facts(match7(), "slt-p18")
    assert got == [f for f in facts7() if f.player == "slt-p18"]
    assert {f.name for f in got} >= {"passes", "distance", "shirt_number"}
    with pytest.raises(ValueError, match="not in a lineup"):
        player_facts(match7(), "slt-p99")


# --- facts at a live moment ---------------------------------------------------------------------


@settings(deadline=None)  # the first example generates the match
@given(st.data())
def test_facts_at_know_only_the_past(data):
    m = match7()
    period = data.draw(periods)
    clock_ms = data.draw(st.integers(0, max(e.clock_ms for e in m.events if e.period == period)))
    now = (period, clock_ms)
    got = facts_at(m, period, clock_ms)
    assert_evidence_inside(got, m)
    assert all(f.end <= now for f in got)
    past = tuple(e for e in m.events if (e.period, e.clock_ms) <= now)
    assert facts_at(dataclasses.replace(m, events=past), period, clock_ms) == got


def test_facts_at_a_moment():
    got = {f.fact_id: f.display for f in facts_at(match7(), 2, 1_343_000)}
    assert got["m7/clock/at-2-1343000/all"] == "67:23"
    assert got["m7/minute/at-2-1343000/all"] == "68'"
    assert got["m7/score/to-2-1343000/all"] == "2–1"
    shares = [v for k, v in got.items() if k.startswith("m7/possession/last5-")]
    assert len(shares) == 2 and sum(int(s[:-1]) for s in shares) == 100


def test_before_anyone_has_the_ball_there_is_no_possession_fact():
    names = {f.name for f in facts_at(match7(), 1, 0)}
    assert "possession" not in names and {"clock", "minute", "score"} <= names


# --- each fact against the stats engine, the league and the clock -------------------------------


def counted_span(all_spells, period=None, window=None):
    """(first, last) of the team spells that overlap the window with some time; None if none."""
    lo, hi = window or (-1, 10**9)
    counted = [
        s
        for s in all_spells
        if s.team is not None
        and (period is None or s.period == period)
        and min(s.end_ms, hi) > max(s.start_ms, lo)
    ]
    if not counted:
        return None
    return (counted[0].period, counted[0].start_ms), (counted[-1].period, counted[-1].end_ms)


def expect(by_id, fact_id, value, unit, display, *, event_ids=None, frame_ids=None, span=None,
           source="engine"):  # fmt: skip
    f = by_id.pop(fact_id)  # each fact once; whatever is left was never expected
    assert (f.value, f.unit, f.display, f.source) == (value, unit, display, source), fact_id
    if event_ids is not None:
        assert f.event_ids == tuple(event_ids), fact_id
    if frame_ids is not None:
        assert f.frame_ids == tuple(frame_ids), fact_id
    if span is not None:
        assert (f.start, f.end) == span, fact_id


def percent_half_up(part: int, whole: int) -> str:
    return half_up_fraction(Fraction(100 * part, whole))


def half_up_fraction(x: Fraction) -> str:
    return str(math.floor(x + Fraction(1, 2)))


# --- readings, derived here with their thresholds written out (the engine's are pinned in
# test_readings.py): (code, phrase) or None
CODE = {phrase: code for code, phrase in VOCABULARY.items()}


def reading(phrase: str | None) -> tuple[str, str] | None:
    return None if phrase is None else (CODE[phrase], phrase)


def score_wanted(difference: int):
    return reading(
        "in the lead" if difference > 0 else "on level terms" if difference == 0 else
        "chasing the game"
    )  # fmt: skip


def goal_wanted(before: int):
    named = {0: "take the lead", -1: "equalise"}
    return reading(named.get(before) or ("extend the lead" if before > 0 else "pull one back"))


def momentum_wanted(pct: int, weight: int):
    if weight < 10:
        return None
    return reading("on top" if pct >= 70 else "pinned back" if pct <= 30 else "evenly matched")


def chaos_wanted(chaos: int):
    return reading(
        "end-to-end" if chaos >= 57 else "patient build-up" if chaos <= 43 else "a steady tempo"
    )


def possession_wanted(pct: int):
    return reading(
        "more of the ball" if pct >= 55 else "less of the ball" if pct <= 45 else
        "an even share of the ball"
    )  # fmt: skip


def goal_readings_wanted(m: Match, events) -> dict:
    """Each goal's reading by fact id: (code, phrase, event ids, span)."""
    teams = (m.meta.home, m.meta.away)
    goals = [e for e in events if e.type is EventType.GOAL]
    want = {}
    for n, g in enumerate(goals):
        before = goals[:n]
        mine = sum(e.team == g.team for e in before)
        theirs = len(before) - mine
        assert g.team in teams
        code, phrase = goal_wanted(mine - theirs)
        span = ((goals[0].period, goals[0].clock_ms), (g.period, g.clock_ms))
        ids = tuple(e.event_id for e in goals[: n + 1])
        want[f"{m.meta.match_id}/goal_reading/at-{g.period}-{g.clock_ms}/{g.team}"] = (
            code, phrase, ids, span,
        )  # fmt: skip
    return want


def flow_wanted(m: Match, events, scope: str, span, period=None, window=None) -> dict:
    """The flow facts of a scope from the stats engine, by fact id: (value, unit, display,
    event ids, span). Pressing spans the scope once its clock has run, momentum once an action
    counts; once a team has had the ball, the changes of possession span the scope, the average
    possession length and the chaos index the team spells counted."""
    meta, rng, want = m.meta, window or (), {}
    for p in pressing(meta, events, period, *rng):
        if p.window_ms:
            rows = {
                "pressing_actions": (p.actions, "", str(p.actions)),
                "pressing_per_minute": (p.per_minute, "per minute", half_up(p.per_minute, 1)),
            }
            for name, row in rows.items():
                want[f"{meta.match_id}/{name}/{scope}/{p.team}"] = (*row, p.event_ids, span)
    mo = momentum(meta, events, period, *rng)
    if mo.event_ids:
        for team, pct in zip(mo.teams, mo.percent, strict=True):
            key = f"{meta.match_id}/momentum/{scope}/{team}"
            want[key] = (pct, "%", f"{pct}%", mo.event_ids, span)
            if (r := momentum_wanted(pct, sum(mo.weights))) is not None:
                key = f"{meta.match_id}/momentum_reading/{scope}/{team}"
                want[key] = (r[0], "", r[1], mo.event_ids, span)
    c = control(events, period, *rng)
    counted = counted_span(spells(events), period, window)
    assert (counted is None) == (c.possessions == 0)
    if counted is not None:
        spell_ids = tuple(i for s in c.spells for i in s.event_ids)
        seconds = c.average_possession_ms / 1000
        rows = {
            "possession_changes": (c.changes, "", str(c.changes), c.change_ids, span),
            "possession_changes_per_minute": (
                c.changes_per_minute, "per minute", half_up(c.changes_per_minute, 1),
                c.change_ids, span,
            ),
            "average_possession_length": (seconds, "s", half_up(seconds, 1), spell_ids, counted),
            "chaos": (c.chaos, "", str(c.chaos), spell_ids, counted),
            "chaos_reading": (*chaos_wanted(c.chaos)[:1], "", chaos_wanted(c.chaos)[1],
                              spell_ids, counted),
        }  # fmt: skip
        for name, row in rows.items():
            want[f"{meta.match_id}/{name}/{scope}/all"] = row
    return want


def expect_flow(by_id, m: Match, events, scope: str, span, period=None) -> None:
    wanted = flow_wanted(m, events, scope, span, period)
    for fact_id, (value, unit, display, ids, fact_span) in wanted.items():
        expect(by_id, fact_id, value, unit, display, event_ids=ids, span=fact_span)


def expect_passing(by_id, scope, who, s, brief=False):
    pct = 100 * s.completed / s.passes
    expect(by_id, f"m7/passes/{scope}/{who}", s.passes, "", str(s.passes), event_ids=s.event_ids)
    expect(by_id, f"m7/passes_completed/{scope}/{who}", s.completed, "", str(s.completed),
           event_ids=s.completed_ids)  # fmt: skip
    expect(by_id, f"m7/pass_completion/{scope}/{who}", pct, "%",
           f"{percent_half_up(s.completed, s.passes)}%", event_ids=s.event_ids)  # fmt: skip
    if brief:
        return
    length = s.average_length_m
    expect(by_id, f"m7/average_pass_length/{scope}/{who}", length, "m", half_up(length, 1),
           event_ids=s.event_ids)  # fmt: skip
    expect(by_id, f"m7/progressive_passes/{scope}/{who}", s.progressive, "", str(s.progressive),
           event_ids=s.progressive_ids)  # fmt: skip
    d = s.average_completed_difficulty
    expect(by_id, f"m7/pass_difficulty/{scope}/{who}", d, "", half_up(d, 0),
           event_ids=s.completed_ids)  # fmt: skip


def test_every_match_fact_is_the_engine_s_number_shown_as_written():
    m, by_id = match7(), {f.fact_id: f for f in facts7()}
    meta, events = m.meta, m.events
    teams = (meta.home, meta.away)
    goals = [e for e in events if e.type is EventType.GOAL]  # in the order they were scored
    expect(by_id, "m7/score/match/all", "3–2", "", "3–2", event_ids=[e.event_id for e in goals])
    for team in teams:
        ids = [e.event_id for e in goals if e.team == team]
        expect(by_id, f"m7/goals/match/{team}", len(ids), "", str(len(ids)), event_ids=ids)
    for team, other in (teams, teams[::-1]):
        diff = sum(e.team == team for e in goals) - sum(e.team == other for e in goals)
        code, phrase = score_wanted(diff)
        expect(by_id, f"m7/score_reading/match/{team}", code, "", phrase,
               event_ids=[e.event_id for e in goals])  # fmt: skip
    for fact_id, (code, phrase, ids, span) in goal_readings_wanted(m, events).items():
        expect(by_id, fact_id, code, "", phrase, event_ids=ids, span=span)
    all_spells = spells(events)
    for scope, period in (("match", None), ("p1", 1), ("p2", 2)):
        p = possession(all_spells, teams, period)
        for team, pct in zip(teams, p.percent, strict=True):
            expect(by_id, f"m7/possession/{scope}/{team}", pct, "%", f"{pct}%",
                   event_ids=p.event_ids, span=counted_span(all_spells, period))  # fmt: skip
            code, phrase = possession_wanted(pct)
            expect(by_id, f"m7/possession_reading/{scope}/{team}", code, "", phrase,
                   event_ids=p.event_ids, span=counted_span(all_spells, period))  # fmt: skip
    last = {p: max(e.clock_ms for e in events if e.period == p) for p in PERIODS}
    expect_flow(by_id, m, events, "match", ((1, 0), (2, last[2])))
    for period in PERIODS:
        expect_flow(by_id, m, events, f"p{period}", ((period, 0), (period, last[period])), period)
    ratings = pass_ratings(meta, events, m.snapshots)
    for team in teams:
        expect_passing(by_id, "match", team, pass_stats(ratings, team=team))
        for period in (1, 2):
            in_period = [r for r in ratings if r.period == period]
            expect_passing(by_id, f"p{period}", team, pass_stats(in_period, team=team))
    numbers = {p.id: p.number for c in load_league().clubs for p in c.players}
    for player in meta.home_lineup + meta.away_lineup:
        if (s := pass_stats(ratings, player=player)).passes:
            expect_passing(by_id, "match", player, s)
        mv = real.moved(7)[player]
        km, kmh = mv.distance_m / 1000, mv.top_speed_ms * 3.6
        expect(by_id, f"m7/distance/match/{player}", km, "km", half_up(km, 1),
               frame_ids=mv.frame_ids)  # fmt: skip
        expect(by_id, f"m7/top_speed/match/{player}", kmh, "km/h", half_up(kmh, 1),
               frame_ids=mv.top_speed_frames)  # fmt: skip
        expect(by_id, f"m7/shirt_number/league/{player}", numbers[player], "",
               str(numbers[player]), span=((1, 0), (1, 0)), source="league")  # fmt: skip
    hard = [b for b in ball_speeds(events) if b.type is EventType.SHOT and b.speed_ms >= 28.0]
    assert HARD_SHOT_MS == 28.0 and hard
    for b in hard:
        kmh = b.speed_ms * 3.6
        expect(
            by_id,
            f"m7/shot_speed/{b.event_id}/{b.player}",
            kmh,
            "km/h",
            half_up(kmh, 0),
            event_ids=[b.event_id],
            span=((b.period, b.clock_ms), (b.period, b.clock_ms)),
        )
    assert not by_id  # no fact without a number behind it


def expected_now(m: Match, period: int, clock_ms: int) -> dict:
    """`facts_at` from the stats engine, by fact id: the display, and for possession the range;
    only the events and the arrived passes up to now."""
    now = (period, clock_ms)
    past = [e for e in m.events if (e.period, e.clock_ms) <= now]
    teams = (m.meta.home, m.meta.away)
    stamp = f"{period}-{clock_ms}"
    want = {}
    goals = [e for e in past if e.type is EventType.GOAL]
    count = {t: sum(e.team == t for e in goals) for t in teams}
    want[f"m7/score/to-{stamp}/all"] = f"{count[teams[0]]}–{count[teams[1]]}"
    for player in m.meta.home_lineup + m.meta.away_lineup:
        number = next(p.number for c in load_league().clubs for p in c.players if p.id == player)
        want[f"m7/shirt_number/league/{player}"] = (str(number), ((1, 0), (1, 0)))
    for team, other in (teams, teams[::-1]):
        want[f"m7/goals/to-{stamp}/{team}"] = str(count[team])
        want[f"m7/score_reading/to-{stamp}/{team}"] = score_wanted(count[team] - count[other])[1]
    for fact_id, (_, phrase, _, span) in goal_readings_wanted(m, past).items():
        if span[1] == now:  # only a goal scored at this instant
            want[fact_id] = (phrase, span)
    all_spells = spells(past)
    window = (clock_ms - 5 * 60_000, clock_ms)  # the last five minutes, once there are five
    scopes = [("to", None, None)] + [("last5", period, window)] * (clock_ms >= 5 * 60_000)
    for scope, p_, w in scopes:
        if (span := counted_span(all_spells, p_, w)) is None:
            continue  # nobody has had the ball: no possession fact
        p = possession(all_spells, teams, p_, *(w or (None, None)))
        for team, pct in zip(teams, p.percent, strict=True):
            want[f"m7/possession/{scope}-{stamp}/{team}"] = (f"{pct}%", span)
            want[f"m7/possession_reading/{scope}-{stamp}/{team}"] = (
                possession_wanted(pct)[1],
                span,
            )
    latest = max((e.period, e.clock_ms) for e in past)  # a live period runs to there
    for scope, p_, w in scopes:
        span = ((1, 0), latest) if w is None else ((period, w[0]), now)
        flow = flow_wanted(m, past, f"{scope}-{stamp}", span, p_, w)
        want |= {i: (display, s) for i, (_, _, display, _, s) in flow.items()}
    arrived = [
        r for r in pass_ratings(m.meta, past, m.snapshots) if (r.period, r.arrival_ms) <= now
    ]
    for team in teams:
        if (s := pass_stats(arrived, team=team)).passes:
            want[f"m7/passes/to-{stamp}/{team}"] = str(s.passes)
            want[f"m7/passes_completed/to-{stamp}/{team}"] = str(s.completed)
            want[f"m7/pass_completion/to-{stamp}/{team}"] = (
                f"{percent_half_up(s.completed, s.passes)}%"
            )
    return want


def check_now(period: int, clock_ms: int) -> None:
    m = match7()
    got = {f.fact_id: f for f in facts_at(m, period, clock_ms)}
    clock = got.pop(f"m7/clock/at-{period}-{clock_ms}/all")
    minute = got.pop(f"m7/minute/at-{period}-{clock_ms}/all")
    assert clock.value == clock.display == display_clock(period, clock_ms)
    assert minute.value + "'" == minute.display == display_minute(period, clock_ms)
    now = (period, clock_ms)
    assert (clock.start, clock.end, clock.source) == (now, now, "clock")
    assert (minute.start, minute.end, minute.source) == (now, now, "clock")
    assert {f.source for f in got.values()} == {"engine", "league"}
    assert all(f.source == "league" for f in got.values() if f.name == "shirt_number")
    want = expected_now(m, period, clock_ms)
    assert set(got) == set(want)
    for fact_id, expected in want.items():
        display, span = expected if isinstance(expected, tuple) else (expected, None)
        assert got[fact_id].display == display, fact_id
        if span is not None:
            assert (got[fact_id].start, got[fact_id].end) == span, fact_id


def edge_moments(m: Match) -> list[tuple[int, int]]:
    """Moments on the edges: at an event, at a pass's arrival and 1 ms before it, 5 minutes
    after a spell ends (where a window starts on its end)."""
    moments = [(e.period, e.clock_ms) for e in m.events]
    for e in m.events:
        if e.type is EventType.PASS:
            arrival = e.clock_ms + e.duration_ms
            moments += [(e.period, arrival - 1), (e.period, arrival)]
    for s in spells(m.events):  # the window starts on its end, or 1 ms before it
        moments += [(s.period, s.end_ms + WINDOW_MS), (s.period, s.end_ms + WINDOW_MS - 1)]
    last = {p: max(e.clock_ms for e in m.events if e.period == p) for p in PERIODS}
    return sorted({(p, c) for p, c in moments if 0 <= c <= last[p]})


@settings(deadline=None)
@given(st.data())
def test_facts_at_are_the_engine_s_numbers_up_to_now(data):
    m = match7()
    period, clock_ms = data.draw(st.sampled_from(edge_moments(m)))
    check_now(period, clock_ms)
    # tracking cut at that instant is enough: no pass in the air is rated
    cut = tuple(s for s in m.snapshots if (s.period, s.clock_ms) <= (period, clock_ms))
    assert facts_at(dataclasses.replace(m, snapshots=cut), period, clock_ms) == facts_at(
        m, period, clock_ms
    )


@pytest.mark.parametrize(
    ("part", "whole", "shown"),
    [(23, 40, "58"), (5, 8, "63"), (1, 8, "13"), (0, 5, "0"), (1, 3, "33"), (2, 3, "67")],
)
def test_percent_rounds_half_up_exactly(part, whole, shown):
    assert _percent(part, whole) == shown


@given(st.integers(1, 2_000), st.data())
def test_percent_is_the_exact_share_rounded_half_up(whole, data):
    part = data.draw(st.integers(0, whole))
    assert _percent(part, whole) == percent_half_up(part, whole)


def clock_time(m: Match, start, end) -> int:
    """Clock time from `start` to `end`, each (period, clock_ms): period 1 runs to its end."""
    (p0, c0), (p1, c1) = start, end
    if p0 == p1:
        return c1 - c0
    first_end = next(
        e.clock_ms for e in m.events if e.period == 1 and e.type is EventType.PERIOD_END
    )
    return first_end - c0 + c1


@settings(deadline=None)
@given(st.data())
def test_a_rate_is_per_minute_of_its_span(data):
    m = match7()
    period, clock_ms = data.draw(st.sampled_from(edge_moments(m)))
    facts = facts_at(m, period, clock_ms) + facts7()
    by_id = {f.fact_id: f for f in facts}
    for count_name, rate_name in (
        ("pressing_actions", "pressing_per_minute"),
        ("possession_changes", "possession_changes_per_minute"),
    ):
        rates = [f for f in facts if f.name == rate_name]
        assert rates and len(rates) == sum(f.name == count_name for f in facts)
        for f in rates:
            count = by_id[f.fact_id.replace(f"/{rate_name}/", f"/{count_name}/")]
            assert (count.start, count.end) == (f.start, f.end)
            assert f.value == count.value * 60_000 / clock_time(m, f.start, f.end), f.fact_id


def test_last_five_minutes_only_once_there_are_five():
    def last5(clock_ms):
        return [f for f in facts_at(match7(), 1, clock_ms) if "/last5-" in f.fact_id]

    assert last5(299_999) == []
    names = sorted(f.name for f in last5(300_000))
    per_team = ["momentum", "possession", "pressing_actions", "pressing_per_minute"]
    # m7 at 05:00: action weights 11 and 14, so momentum has a reading (counted 23 Oct)
    per_team += ["momentum_reading", "possession_reading"]
    once = [
        "average_possession_length",
        "chaos",
        "chaos_reading",
        "possession_changes",
        "possession_changes_per_minute",
    ]
    assert names == sorted(per_team * 2 + once)


def test_no_facts_after_the_period_ended():
    m = match7()
    end = next(e.clock_ms for e in m.events if e.period == 1 and e.type is EventType.PERIOD_END)
    assert facts_at(m, 1, end)
    with pytest.raises(ValueError, match="ended"):
        facts_at(m, 1, end + 1)


def test_facts_at_on_the_edges_of_a_goal_and_a_pass():
    m = match7()
    goal = next(e for e in m.events if e.type is EventType.GOAL)
    check_now(goal.period, goal.clock_ms)  # the goal counts at its own instant
    p = next(e for e in m.events if e.type is EventType.PASS and e.clock_ms > 60_000)
    arrival = p.clock_ms + p.duration_ms

    def passes(clock_ms):
        team = f"m7/passes/to-{p.period}-{clock_ms}/{p.team}"
        return next(f.value for f in facts_at(m, p.period, clock_ms) if f.fact_id == team)

    assert passes(arrival) == passes(arrival - 1) + 1  # counted once it arrives, not before
    spell = next(s for s in spells(m.events) if s.team and s.start_ms > WINDOW_MS)
    check_now(spell.period, spell.end_ms + WINDOW_MS)  # the window starts where it ends

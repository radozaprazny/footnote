"""Facts: every number a narrative may use, with the evidence it comes from.

A fact's `display` is the numeral exactly as a narrative writes it (`52%`, `12.7`, `67:23`,
`68'`, `3–2`) and `unit` the word after it, so the Guard (M3) compares the numerals of a text with
displays. `event_ids` and `frame_ids` name the evidence; `start` and `end`, each (period,
clock_ms), bound it. `fact_id` is stable: a match gives the same facts and ids on every run.
`source` says where a fact comes from: `engine` (the stats engine), `league` (the squads) or
`clock` (the match clock).

A reading (`*_reading`, `stats.readings`) is the engine's judgement of another fact: its `value`
is the reading's code, its `display` the phrase a narrative writes ("take the lead", "on top"),
its `unit` empty. It has the scope, team, range and evidence of the fact it reads, so its id
mirrors that fact's (`m7/momentum_reading/last5-1-991105/vel` reads `m7/momentum/last5-…/vel`).
"""

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal

from matchlens.events import Event, EventType, Outcome, display_clock
from matchlens.league import load_league
from matchlens.match import Match, Snapshot
from matchlens.stats.flow import control, momentum, pressing
from matchlens.stats.passing import PassRating, pass_ratings, pass_stats
from matchlens.stats.possession import Spell, possession, spells
from matchlens.stats.readings import (
    VOCABULARY,
    chaos_reading,
    goal_reading,
    momentum_reading,
    possession_reading,
    score_reading,
)
from matchlens.stats.speed import hard_shot_tags, movement

KMH_PER_MS = 3.6
WINDOW_MS = 5 * 60_000  # the rolling window of `facts_at`

Time = tuple[int, int]  # (period, clock_ms)
Span = tuple[Time, Time]


@dataclass(frozen=True)
class Fact:
    fact_id: str
    match_id: str
    name: str
    value: int | float | str
    unit: str
    display: str
    source: str
    start: Time
    end: Time
    team: str | None = None
    player: str | None = None
    event_ids: tuple[str, ...] = ()
    frame_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """Plain JSON types: tuples become lists."""
        return asdict(self) | {
            "start": list(self.start),
            "end": list(self.end),
            "event_ids": list(self.event_ids),
            "frame_ids": list(self.frame_ids),
        }


def brief(fact: Fact) -> dict:
    """A fact without its id lists (a possession fact cites about 1 700 events), with their sizes
    instead: what the MCP server sends and a moment case carries."""
    d = {k: v for k, v in fact.to_dict().items() if k not in ("event_ids", "frame_ids")}
    return d | {"event_count": len(fact.event_ids), "frame_count": len(fact.frame_ids)}


def match_facts(match: Match) -> list[Fact]:
    """The facts of a whole match: score, possession (match and periods), passing (teams for the
    match and each period, players for the match), pressing, momentum and control vs chaos (match
    and periods), distance and top speed per player, hard shots, and shirt numbers; the readings
    of score, possession, momentum and chaos, and of every goal. Tracking takes one pass over the
    frames (about 4 s a match)."""
    meta, events = match.meta, match.events
    facts = _Facts(match)
    whole = ((1, 0), (2, _end(match, 2)))
    facts.score(events, whole, "match")
    facts.goal_readings(events)
    all_spells = spells(events)
    ratings = pass_ratings(meta, events, _arrivals(match, events))
    facts.possession(all_spells, "match")
    facts.passing(ratings, "match", whole, team=meta.home)
    facts.passing(ratings, "match", whole, team=meta.away)
    facts.flow(events, "match", whole)
    for period in (1, 2):
        span = ((period, 0), (period, _end(match, period)))
        in_period = [r for r in ratings if r.period == period]
        facts.possession(all_spells, f"p{period}", period)
        facts.passing(in_period, f"p{period}", span, team=meta.home)
        facts.passing(in_period, f"p{period}", span, team=meta.away)
        facts.flow(events, f"p{period}", span, period)
    lineups = meta.home_lineup + meta.away_lineup
    for player in lineups:
        facts.passing(ratings, "match", whole, player=player)
    for player, m in movement(match.frames()).items():
        km = m.distance_m / 1000
        facts.add(
            "distance",
            km,
            "km",
            _rounded(km, 1),
            whole,
            "match",
            player=player,
            frame_ids=m.frame_ids,
        )
        if m.top_speed_frames:
            kmh = m.top_speed_ms * KMH_PER_MS
            facts.add(
                "top_speed",
                kmh,
                "km/h",
                _rounded(kmh, 1),
                whole,
                "match",
                player=player,
                frame_ids=m.top_speed_frames,
            )
    for tag in hard_shot_tags(events):
        kmh = tag.speed_ms * KMH_PER_MS
        at = (tag.period, tag.clock_ms)
        facts.add(
            "shot_speed",
            kmh,
            "km/h",
            _rounded(kmh, 0),
            (at, at),
            tag.source_ids[0],
            player=tag.player,
            event_ids=tag.source_ids,
        )
    facts.shirt_numbers()
    return facts.all


def player_facts(match: Match, player: str) -> list[Fact]:
    """The facts of one player of the match."""
    if player not in match.meta.home_lineup + match.meta.away_lineup:
        raise ValueError(f"{match.meta.match_id}: {player} is not in a lineup")
    return [f for f in match_facts(match) if f.player == player]


def facts_at(match: Match, period: int, clock_ms: int) -> list[Fact]:
    """What is known at (period, clock_ms) of a live match: the clock and the minute, the score,
    possession, pressing, momentum and control vs chaos so far and, from the fifth minute of a
    period, over its last five minutes, the teams' passing so far, and the shirt numbers; the
    readings of score, possession, momentum and chaos, and of a goal scored at that instant.

    Only events up to that instant count, and for passing only passes that have arrived by then,
    so tracking up to that instant is enough; momentum counts a completed pass when it is played,
    as its event carries the outcome. Players' passing, shot speeds and the tracking facts are
    whole-match only (`match_facts`, Follow-ups). A moment after the period's end is refused.
    """
    meta = match.meta
    clock = display_clock(period, clock_ms)  # also checks period and clock
    ends = [
        e.clock_ms for e in match.events if e.period == period and e.type is EventType.PERIOD_END
    ]
    if ends and clock_ms > ends[0]:
        raise ValueError(
            f"{meta.match_id}: period {period} ended at {display_clock(period, ends[0])}"
        )
    now = (period, clock_ms)
    events = [e for e in match.events if (e.period, e.clock_ms) <= now]
    stamp = f"{period}-{clock_ms}"
    facts = _Facts(match)
    minute = display_minute(period, clock_ms)
    facts.add("clock", clock, "", clock, (now, now), f"at-{stamp}", source="clock")
    facts.add("minute", minute[:-1], "", minute, (now, now), f"at-{stamp}", source="clock")
    so_far = ((1, 0), now)
    facts.score(events, so_far, f"to-{stamp}")
    facts.goal_readings(events, at=now)
    all_spells = spells(events)
    facts.possession(all_spells, f"to-{stamp}")
    # the engine knows the match up to its latest event, so its rates run to there
    latest = max(((e.period, e.clock_ms) for e in events), default=now)
    facts.flow(events, f"to-{stamp}", ((1, 0), latest))
    if clock_ms >= WINDOW_MS:  # earlier the window would not be five minutes
        window = (clock_ms - WINDOW_MS, clock_ms)
        facts.possession(all_spells, f"last5-{stamp}", period, window)
        facts.flow(events, f"last5-{stamp}", ((period, window[0]), now), period, window)
    arrived = [
        e
        for e in events
        if e.type is not EventType.PASS or (e.period, e.clock_ms + e.duration_ms) <= now
    ]
    ratings = pass_ratings(meta, arrived, _arrivals(match, arrived))
    for team in (meta.home, meta.away):
        facts.passing(ratings, f"to-{stamp}", so_far, team=team, brief=True)
    facts.shirt_numbers()
    return facts.all


def display_minute(period: int, clock_ms: int) -> str:
    """The minute being played, as football counts it: 67:23 is the 68th minute (`68'`), and
    45+2:13 the third minute of stoppage time (`45+3'`)."""
    minutes = display_clock(period, clock_ms).split(":")[0]
    if "+" in minutes:
        base, extra = minutes.split("+")
        return f"{base}+{int(extra) + 1}'"
    return f"{int(minutes) + 1}'"


def _rounded(value: float, places: int) -> str:
    """The display of a number: rounded half up, as people do (62.5 % shows as 63 %)."""
    return str(Decimal(repr(value)).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP))


def _percent(part: int, whole: int) -> str:
    """`part` of `whole` in whole per cent, rounded half up in integers: 23 of 40 shows 58."""
    return str((200 * part + whole) // (2 * whole))


def _end(match: Match, period: int) -> int:
    return max(e.clock_ms for e in match.events if e.period == period)


def _arrivals(match: Match, events: Sequence[Event]) -> tuple[Snapshot, ...]:
    """The tracking at the instants the complete passes among `events` arrive: what
    `pass_ratings` reads."""
    return match.snapshots_at(
        (e.period, e.clock_ms + e.duration_ms)
        for e in events
        if e.type is EventType.PASS and e.outcome is Outcome.COMPLETE
    )


def _spells_span(counted: Sequence[Spell]) -> Span:
    """From the start of the first spell to the end of the last."""
    return (counted[0].period, counted[0].start_ms), (counted[-1].period, counted[-1].end_ms)


class _Facts:
    """Collects the facts of one match."""

    def __init__(self, match: Match) -> None:
        self.match = match
        self.all: list[Fact] = []

    def add(
        self,
        name,
        value,
        unit,
        display,
        span: Span,
        scope,
        *,
        team=None,
        player=None,
        event_ids=(),
        frame_ids=(),
        source="engine",
    ) -> None:
        match_id = self.match.meta.match_id
        fact_id = f"{match_id}/{name}/{scope}/{player or team or 'all'}"
        self.all.append(
            Fact(
                fact_id,
                match_id,
                name,
                value,
                unit,
                display,
                source,
                *span,
                team,
                player,
                tuple(event_ids),
                tuple(frame_ids),
            )
        )

    def score(self, events, span: Span, scope: str) -> None:
        meta = self.match.meta
        goals = [e for e in events if e.type is EventType.GOAL]
        by_team = {t: [e.event_id for e in goals if e.team == t] for t in (meta.home, meta.away)}
        score = f"{len(by_team[meta.home])}–{len(by_team[meta.away])}"
        goal_ids = [e.event_id for e in goals]
        self.add("score", score, "", score, span, scope, event_ids=goal_ids)
        for team, ids in by_team.items():
            self.add("goals", len(ids), "", str(len(ids)), span, scope, team=team, event_ids=ids)
        for team, other in ((meta.home, meta.away), (meta.away, meta.home)):
            code = score_reading(len(by_team[team]) - len(by_team[other]))
            self.reading("score_reading", code, span, scope, team=team, event_ids=goal_ids)

    def goal_readings(self, events, at: Time | None = None) -> None:
        """What each goal did for its team, as an `at` fact of its instant; with `at`, only a
        goal scored at that instant. Its evidence: the goals up to and including it, so its range
        runs from the match's first goal to it."""
        diff = dict.fromkeys((self.match.meta.home, self.match.meta.away), 0)
        so_far: list[str] = []
        first: Time | None = None
        for e in events:
            if e.type is not EventType.GOAL:
                continue
            now = (e.period, e.clock_ms)
            first = first or now
            so_far.append(e.event_id)
            other = next(t for t in diff if t != e.team)
            code = goal_reading(diff[e.team] - diff[other])
            diff[e.team] += 1
            if at is None or now == at:
                scope = f"at-{e.period}-{e.clock_ms}"
                self.reading(
                    "goal_reading", code, (first, now), scope, team=e.team, event_ids=so_far
                )

    def reading(self, name: str, code: str, span: Span, scope, *, team=None, event_ids=()) -> None:
        self.add(name, code, "", VOCABULARY[code], span, scope, team=team, event_ids=event_ids)

    def possession(self, all_spells: list[Spell], scope, period=None, window=None) -> None:
        """Possession per team. Its time range runs from the first to the last spell counted,
        so for a window it may start before the window (owner decided 20 Oct); without any
        spell, 50/50 has no evidence and is no fact. Shares use the largest remainder, so the
        two always sum to 100."""
        teams = (self.match.meta.home, self.match.meta.away)
        lo, hi = window or (-math.inf, math.inf)
        counted = [
            s
            for s in all_spells
            if s.team is not None
            and period in (None, s.period)
            and min(s.end_ms, hi) > max(s.start_ms, lo)
        ]
        if not counted:
            return
        span = _spells_span(counted)
        p = possession(all_spells, teams, period, *(window or ()))
        for team, pct in zip(teams, p.percent, strict=True):
            self.add(
                "possession", pct, "%", f"{pct}%", span, scope, team=team, event_ids=p.event_ids
            )
            code = possession_reading(pct)
            self.reading("possession_reading", code, span, scope, team=team, event_ids=p.event_ids)

    def passing(
        self, ratings: list[PassRating], scope, span: Span, *, team=None, player=None, brief=False
    ) -> None:
        """Pass facts of a team or a player; `brief`: the counts and the completion only."""
        s = pass_stats(ratings, team=team, player=player)
        if not s.passes:
            return
        pct = 100 * s.completed / s.passes
        rows = [
            ("passes", s.passes, "", str(s.passes), s.event_ids),
            ("passes_completed", s.completed, "", str(s.completed), s.completed_ids),
            ("pass_completion", pct, "%", f"{_percent(s.completed, s.passes)}%", s.event_ids),
        ]
        if not brief:
            length, d = s.average_length_m, s.average_completed_difficulty
            rows += [
                ("average_pass_length", length, "m", _rounded(length, 1), s.event_ids),
                ("progressive_passes", s.progressive, "", str(s.progressive), s.progressive_ids),
            ]
            if d is not None:
                rows.append(("pass_difficulty", d, "", _rounded(d, 0), s.completed_ids))
        for name, value, unit, display, ids in rows:
            self.add(
                name, value, unit, display, span, scope, team=team, player=player, event_ids=ids
            )

    def flow(self, events, scope, span: Span, period=None, window=None) -> None:
        """Pressing per team, the momentum shares and control vs chaos. Counts and rates span the
        scope, whose clock time a rate is per minute of; the average possession length and the
        chaos index span the spells they count, as possession does. No fact without anything
        behind it: no pressing before the clock has run, no momentum before an action counts, no
        control before a team has had the ball."""
        meta, rng = self.match.meta, window or ()
        for p in pressing(meta, events, period, *rng):
            if p.window_ms:
                for name, value, unit, display in (
                    ("pressing_actions", p.actions, "", str(p.actions)),
                    ("pressing_per_minute", p.per_minute, "per minute", _rounded(p.per_minute, 1)),
                ):
                    self.add(
                        name, value, unit, display, span, scope, team=p.team, event_ids=p.event_ids
                    )
        m = momentum(meta, events, period, *rng)
        if m.event_ids:
            for team, pct in zip(m.teams, m.percent, strict=True):
                self.add(
                    "momentum", pct, "%", f"{pct}%", span, scope, team=team, event_ids=m.event_ids
                )
                if code := momentum_reading(pct, sum(m.weights)):
                    self.reading(
                        "momentum_reading", code, span, scope, team=team, event_ids=m.event_ids
                    )
        c = control(events, period, *rng)
        if not c.possessions:
            return
        spells_span = _spells_span(c.spells)
        spell_ids = [i for s in c.spells for i in s.event_ids]
        rate, seconds = c.changes_per_minute, c.average_possession_ms / 1000
        rows = [
            ("possession_changes", c.changes, "", str(c.changes), span, c.change_ids),
            ("possession_changes_per_minute", rate, "per minute", _rounded(rate, 1), span,
             c.change_ids),
            ("average_possession_length", seconds, "s", _rounded(seconds, 1), spells_span,
             spell_ids),
            ("chaos", c.chaos, "", str(c.chaos), spells_span, spell_ids),
        ]  # fmt: skip
        for name, value, unit, display, fact_span, ids in rows:
            self.add(name, value, unit, display, fact_span, scope, event_ids=ids)
        self.reading(
            "chaos_reading", chaos_reading(c.chaos), spells_span, scope, event_ids=spell_ids
        )

    def shirt_numbers(self) -> None:
        """From the league, so known before the kick-off: the same fact at any moment."""
        meta = self.match.meta
        numbers = {p.id: p.number for c in load_league().clubs for p in c.players}
        kick_off = ((1, 0), (1, 0))
        for player in meta.home_lineup + meta.away_lineup:
            n = numbers[player]
            self.add(
                "shirt_number", n, "", str(n), kick_off, "league", player=player, source="league"
            )

"""The flow of play: how hard each team presses, which team has the momentum, and whether the game
is under control or chaotic.

A window is what `possession` takes: the whole match, one period, or a clock range of one period
(a rolling window ends at the current clock). An event counts when its clock lies in the range,
both ends included; time on the ball counts by its overlap with the range, as in `possession`;
a change of possession counts from its start to just before its end, as the new team has had
no time on the ball at the end yet (so adjacent windows add up).
A window lasts its clock time: a period runs to its `period_end` or, while it has not ended, to
the clock of its latest event; a range is cut at the end of a period that has ended. Spots are
seen from the acting team, as in `matchlens.stats.passing`, so turning the pitch round and
swapping the teams' ends changes nothing. Every value works on any prefix of the event stream
(live use) and carries the event ids it counts.
"""

import itertools
import math
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from typing import Self

from matchlens.events import PITCH_LENGTH, Event, EventType, MatchMeta, Outcome, Point
from matchlens.match import attacking_goal_x
from matchlens.stats.passing import Zone, in_opponent_half, team_frame, zone
from matchlens.stats.possession import WINS, Spell, check_window, percent_shares, spells

MS_PER_MINUTE = 60_000
PRESSING = frozenset({EventType.PRESSURE, EventType.TACKLE})  # with any outcome
SHOT_WEIGHT = 3  # momentum: a shot; a pass into the final third or a ball won high weighs 1
_BALL_WINS = frozenset({EventType.INTERCEPTION, EventType.RECOVERY})
# a whole match of the league, medians over seeds 0–49 (PROGRESS.md, Metrics): both score 50
TYPICAL_CHANGES_PER_MINUTE = Fraction(3)  # p50 3.03, range 2.67–3.32
TYPICAL_POSSESSION_MS = 16_400  # p50 16.4 s, range 15.1–18.2 s
NEUTRAL = 50  # a momentum share and the chaos index when the window holds nothing to go on


@dataclass(frozen=True)
class Pressing:
    """How hard one team pressed: its pressures and tackles in the opponent's half."""

    team: str
    actions: int
    window_ms: int
    per_minute: float  # 0.0 while no clock time has passed
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class Momentum:
    """Who is on top: each team's share (in the order of `teams`, summing to 100) of the weighted
    attacking actions, and those actions of both teams, in order."""

    teams: tuple[str, str]
    weights: tuple[int, int]
    percent: tuple[int, int]
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class Control:
    """Control vs chaos: how often the ball changed teams, and how long the teams kept it.

    A possession is one team's run of spells within a period: a spell without a team in between
    (a loose ball the team gets back, a foul against it, a corner after a parried save) does not
    end it. A change of possession is the next possession going to the other team, in play or
    at a restart (a throw-in, a goal kick, the kick-off after a goal), never over half-time;
    `change_ids` are the events with which the other team got the ball. `possessions` and
    `average_possession_ms` count the possessions with time on the ball in the window.
    `chaos` runs from 0 (control) to 100 (chaos), `NEUTRAL` when no team had the ball in the
    window. `spells` are the spells counted, whole.
    """

    window_ms: int
    ball_ms: int  # time a team had the ball
    possessions: int
    changes: int
    changes_per_minute: float
    average_possession_ms: float | None  # ball time per possession, None without one
    chaos: int
    change_ids: tuple[str, ...]
    spells: tuple[Spell, ...]


def pressing(
    meta: MatchMeta,
    events: Iterable[Event],
    period: int | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> tuple[Pressing, Pressing]:
    """Pressing intensity of the home and the away team: the pressures and tackles (any outcome)
    a team makes with the ball in the opponent's half, and how many per minute of the window."""
    events = list(events)
    window = _Window.of(events, period, start_ms, end_ms)
    ids: dict[str, list[str]] = {meta.home: [], meta.away: []}
    for e in events:
        if e.type in PRESSING and window.holds(e) and in_opponent_half(_frame(meta, e, e.start)[0]):
            ids[e.team].append(e.event_id)
    return tuple(
        Pressing(team, len(i), window.ms, _per_minute(len(i), window.ms), tuple(i))
        for team, i in ids.items()
    )


def momentum(
    meta: MatchMeta,
    events: Iterable[Event],
    period: int | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> Momentum:
    """Momentum over a window: each team's share of the attacking actions, weighted by
    `attacking_weight`; `NEUTRAL` each while the window holds none."""
    events = list(events)
    window = _Window.of(events, period, start_ms, end_ms)
    teams = (meta.home, meta.away)
    weights = dict.fromkeys(teams, 0)
    ids = []
    for e in events:
        if window.holds(e) and (weight := attacking_weight(meta, e)):
            if e.team not in weights:
                raise ValueError(f"{e.event_id}: {e.team} is not one of {list(teams)}")
            weights[e.team] += weight
            ids.append(e.event_id)
    totals = tuple(weights.values())
    return Momentum(teams, totals, tuple(percent_shares(totals)), tuple(ids))


def attacking_weight(meta: MatchMeta, e: Event) -> int:
    """What an event adds to its team's momentum: `SHOT_WEIGHT` for a shot; 1 for a completed
    pass or clearance that ends in the final third, and for winning the ball in the opponent's
    half (a won tackle, a pressure that regains it, an interception, a recovery); else 0."""
    if e.type is EventType.SHOT:
        return SHOT_WEIGHT
    if e.type in (EventType.PASS, EventType.CLEARANCE):
        complete = e.outcome is Outcome.COMPLETE
        return int(complete and zone(*_frame(meta, e, e.end)) >= Zone.FINAL_THIRD)
    if e.type in _BALL_WINS or e.outcome in WINS:
        return int(in_opponent_half(_frame(meta, e, e.start)[0]))
    return 0


def control(
    events: Iterable[Event],
    period: int | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> Control:
    """Control vs chaos over a window, from the possession spells (`possession.spells`)."""
    events = list(events)
    window = _Window.of(events, period, start_ms, end_ms)
    on_ball = [s for s in spells(events) if s.team is not None]
    counted = [s for s in on_ball if window.overlap(s) > 0]
    if not counted:
        return Control(window.ms, 0, 0, 0, 0.0, None, NEUTRAL, (), ())
    ball_ms = sum(window.overlap(s) for s in counted)
    # a possession ends where the period or the team changes
    possessions = 1 + sum(
        (a.period, a.team) != (b.period, b.team) for a, b in itertools.pairwise(counted)
    )
    # a change: the other team's spell after this team's in a period, starting in the window
    change_ids = [
        b.event_ids[0]
        for a, b in itertools.pairwise(on_ball)
        if a.period == b.period and a.team != b.team and window.starts(b)
    ]
    # time on the ball lies inside the window, so the window has lasted
    rate = Fraction(len(change_ids) * MS_PER_MINUTE, window.ms)
    average = Fraction(ball_ms, possessions)
    return Control(
        window_ms=window.ms,
        ball_ms=ball_ms,
        possessions=possessions,
        changes=len(change_ids),
        changes_per_minute=float(rate),
        average_possession_ms=float(average),
        chaos=chaos_index(rate, average),
        change_ids=tuple(change_ids),
        spells=tuple(counted),
    )


def chaos_index(changes_per_minute: Fraction, average_possession_ms: Fraction) -> int:
    """Control (0) to chaos (100): the mean of how often the ball changes teams and how short
    the possessions are, each as a share that a typical whole match puts at one half. Exact,
    rounded half up."""
    if changes_per_minute < 0 or average_possession_ms <= 0:
        raise ValueError("needs changes per minute >= 0 and a possession that lasted")
    often = changes_per_minute / (changes_per_minute + TYPICAL_CHANGES_PER_MINUTE)
    short = TYPICAL_POSSESSION_MS / (average_possession_ms + TYPICAL_POSSESSION_MS)
    return math.floor(50 * (often + short) + Fraction(1, 2))


@dataclass(frozen=True)
class _Window:
    period: int | None
    lo: float  # the clock range, both ends included
    hi: float
    ms: int  # the clock time it lasts

    @classmethod
    def of(
        cls, events: list[Event], period: int | None, start_ms: int | None, end_ms: int | None
    ) -> Self:
        check_window(period, start_ms, end_ms)
        lengths: dict[int, int] = {}
        for e in events:
            lengths[e.period] = max(lengths.get(e.period, 0), e.clock_ms)
        lo = -math.inf if start_ms is None else start_ms
        hi = math.inf if end_ms is None else end_ms
        if period is None:
            ms = sum(lengths.values())
        else:
            length = lengths.get(period, 0)
            ended = any(e.period == period and e.type is EventType.PERIOD_END for e in events)
            end = length if end_ms is None or (ended and end_ms > length) else end_ms
            ms = max(0, end - max(start_ms or 0, 0))
        return cls(period, lo, hi, ms)

    def holds(self, e: Event) -> bool:
        """Both ends included, so two adjacent windows both count an event on their edge."""
        return self.period in (None, e.period) and self.lo <= e.clock_ms <= self.hi

    def starts(self, s: Spell) -> bool:
        """`s` starts in the window, its end excluded: then it has time on the ball in it."""
        return self.period in (None, s.period) and self.lo <= s.start_ms < self.hi

    def overlap(self, s: Spell) -> float:
        if self.period not in (None, s.period):
            return 0
        return min(s.end_ms, self.hi) - max(s.start_ms, self.lo)


def _frame(meta: MatchMeta, e: Event, spot: Point) -> tuple[int, int]:
    """`spot` in the frame of the team that acts in `e`, centimetres."""
    rightwards = attacking_goal_x(meta, e.team, e.period) == PITCH_LENGTH
    return team_frame(spot.x, spot.y, rightwards)


def _per_minute(count: int, ms: int) -> float:
    return count * MS_PER_MINUTE / ms if ms else 0.0

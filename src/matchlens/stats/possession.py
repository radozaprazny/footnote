"""Possession statistics: spells from the event stream, and time on the ball per team."""

import operator
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from matchlens.events import PERIODS, Event, EventType, Outcome

# events that give the actor's team the ball; a tackle or a pressure only when it wins the ball
_GAINS = frozenset(
    {
        EventType.PASS,
        EventType.SHOT,
        EventType.CLEARANCE,
        EventType.INTERCEPTION,
        EventType.SAVE,
        EventType.RECOVERY,
    }
)
WINS = frozenset({Outcome.WON, Outcome.REGAIN})  # outcomes that win the ball


@dataclass(frozen=True)
class Spell:
    """A stretch of one period in which one team has the ball.

    `team` is None while nobody has it: the ball is loose or out of play. `event_ids` are the
    events that happened in the spell, in order: the event that gave the team the ball first.
    An event that changes possession when no time is left for it is in no spell: a save the
    keeper parries out for a corner, or the latest event of a prefix (until the next arrives).
    """

    team: str | None
    period: int
    start_ms: int
    end_ms: int
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class Possession:
    """Time on the ball per team (in the order asked for), its integer shares, and the events
    of every spell counted."""

    teams: tuple[str, ...]
    ms: tuple[int, ...]
    percent: tuple[int, ...]
    event_ids: tuple[str, ...]


def spells(events: Iterable[Event]) -> list[Spell]:
    """Possession spells of a match, or of any prefix of its event stream (live use).

    A team has the ball from an event that gives it the ball (pass, shot, clearance,
    interception, save, recovery, a won tackle, a pressure that regains it) until the other
    team gets it, a ball the team plays lands anywhere but at a team-mate (a failed pass or
    clearance, any shot), or a foul stops play. A restart means the ball was out of play since
    the latest earlier event, or the end of its ball flight. The spells of a period tile it
    from 0 to its `period_end` without gaps, consecutive spells differ in team, and none is
    empty. A period that has not ended yet runs to the clock of its latest event: nothing later
    is known, so a prefix gives exactly the spells of the whole match up to that clock.
    """
    by_period: dict[int, list[Event]] = {}
    for e in events:
        by_period.setdefault(e.period, []).append(e)
    return [s for period in sorted(by_period) for s in _period_spells(period, by_period[period])]


def possession(
    spells: Iterable[Spell],
    teams: Sequence[str],
    period: int | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> Possession:
    """Possession of `teams` over the match, one period, or a clock range of one period.

    A rolling window is the range that ends at the current clock. Time without a team counts
    for nobody; while no team has had the ball, the shares split 100 equally.
    """
    check_window(period, start_ms, end_ms)
    if len(set(teams)) != len(teams):
        raise ValueError("teams must be distinct")
    ms = dict.fromkeys(teams, 0)
    event_ids: list[str] = []
    for s in spells:
        if s.team is None or (period is not None and s.period != period):
            continue
        if s.team not in ms:
            raise ValueError(f"{s.team} has the ball but is not one of {list(teams)}")
        start = s.start_ms if start_ms is None else max(s.start_ms, start_ms)
        end = s.end_ms if end_ms is None else min(s.end_ms, end_ms)
        if end > start:
            ms[s.team] += end - start
            event_ids.extend(s.event_ids)
    times = tuple(ms.values())
    return Possession(tuple(teams), times, tuple(percent_shares(times)), tuple(event_ids))


def check_window(period: int | None, start_ms: int | None, end_ms: int | None) -> None:
    """A window is the whole match (no period), one period, or a clock range of one period."""
    if period is None and (start_ms is not None or end_ms is not None):
        raise ValueError("a clock range needs a period")
    if period is not None and period not in PERIODS:
        raise ValueError(f"period = {period!r} is not one of {PERIODS}")
    if start_ms is not None and end_ms is not None and start_ms > end_ms:
        raise ValueError(f"the range {start_ms}-{end_ms} ends before it starts")


def _period_spells(period: int, events: list[Event]) -> list[Spell]:
    # one state per change of possession: [team, start, event ids]; it ends where the next starts
    states: list[list] = [[None, 0, []]]

    def switch(team: str | None, at: int) -> None:
        if states[-1][0] != team:
            states.append([team, at, []])

    lands_loose = None  # when the ball the team in possession played lands loose
    settled = 0  # when the latest event, or its ball flight, ends
    end = None
    for e in events:
        t = e.clock_ms
        if lands_loose is not None and lands_loose <= t:
            switch(None, lands_loose)
            lands_loose = None
        if e.restart is not None:
            switch(None, min(settled, t))
        if e.type in _GAINS or e.outcome in WINS:
            switch(e.team, t)
            lands_loose = None
            if e.duration_ms is not None and e.outcome is not Outcome.COMPLETE:
                lands_loose = t + e.duration_ms
        elif e.type is EventType.FOUL:
            switch(None, t)
            lands_loose = None
        states[-1][2].append(e.event_id)
        settled = max(settled, t + (e.duration_ms or 0))
        end = t
        if e.type is EventType.PERIOD_END:
            break
    merged: list[Spell] = []
    stops = [state[1] for state in states[1:]] + [end]
    for (team, start, event_ids), stop in zip(states, stops, strict=True):
        if merged and merged[-1].team == team:
            last = merged[-1]
            merged[-1] = Spell(team, period, last.start_ms, stop, last.event_ids + tuple(event_ids))
        elif stop > start:
            merged.append(Spell(team, period, start, stop, tuple(event_ids)))
        # else no time passed, so the state goes with its events: e.g. a save that the keeper
        # parries out for a corner, or the latest event of a prefix when it changes possession
    return merged


def percent_shares(counts: Sequence[int]) -> list[int]:
    """Integer percentages of `counts` that sum to exactly 100.

    Largest remainder method: every share is the floor of its exact proportion, and the points
    left over go to the largest remainders, ties to the lower index. All-zero counts split 100
    equally. Integer arithmetic only, so the result is exact and deterministic.
    """
    counts = list(counts)
    if any(isinstance(c, bool) for c in counts):
        raise TypeError("counts must be ints, not bools")
    # operator.index rejects floats and turns int-like values (e.g. numpy ints) into Python ints
    counts = [operator.index(c) for c in counts]
    if not counts:
        raise ValueError("counts must not be empty")
    if any(c < 0 for c in counts):
        raise ValueError("counts must not be negative")

    weights = counts if any(counts) else [1] * len(counts)
    total = sum(weights)

    shares = [100 * w // total for w in weights]
    leftover = 100 - sum(shares)
    # sorted() is stable, so equal remainders keep index order
    by_remainder = sorted(range(len(weights)), key=lambda i: -(100 * weights[i] % total))
    for i in by_remainder[:leftover]:
        shares[i] += 1
    return shares

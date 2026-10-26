"""Pass quality: a rating for every pass, from its event and the tracking where the ball arrives,
and per player or team the counts and averages of those ratings.

Geometry is computed in whole centimetres (coordinates are stored to the centimetre) and in the
frame of the team that passes, so mirroring the pitch and swapping the teams' ends gives exactly
the same ratings.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum

from matchlens.events import (
    PITCH_LENGTH,
    PITCH_WIDTH,
    Event,
    EventType,
    MatchMeta,
    Outcome,
    team_of,
)
from matchlens.match import (
    PENALTY_AREA_HALF_WIDTH,
    PENALTY_AREA_LENGTH,
    Snapshot,
    attacking_goal_x,
)

# weights of the difficulty rating; they sum to 100
LENGTH_WEIGHT, PRESSURE_WEIGHT, DIRECTION_WEIGHT, ZONE_WEIGHT = 40, 30, 15, 15
LONGEST_M = 60.0  # a pass this long or longer is as long as it gets
CLOSE_M = 10.0  # an opponent nearer to the receiver than this adds pressure
# progressive pass (Wyscout): metres closer to the goal attacked, by the halves it starts and
# ends in (is it in the opponent's half?)
PROGRESS_M = {(False, False): 30.0, (False, True): 15.0, (True, True): 10.0}

_LENGTH, _WIDTH = round(PITCH_LENGTH * 100), round(PITCH_WIDTH * 100)  # centimetres


class Zone(IntEnum):
    """Where a pass ends, seen from the team that plays it."""

    OWN_THIRD = 0
    MIDDLE_THIRD = 1
    FINAL_THIRD = 2
    PENALTY_AREA = 3  # the one the team attacks


@dataclass(frozen=True)
class PassRating:
    event_id: str
    period: int
    clock_ms: int  # when the pass is played
    arrival_ms: int  # when the ball arrives
    team: str
    player: str
    complete: bool
    length_m: float
    forward: float  # cosine of the angle between the pass and the direction of attack
    opponent_m: float | None  # where the ball arrives to the nearest opponent, at that instant
    zone: Zone  # where the ball ended
    # a complete open-play pass that gets the ball much closer to the centre of the goal; unlike
    # `forward`, which looks along the pitch, so a square pass near the box can be progressive
    progressive: bool
    difficulty: int | None  # 0 easy to 100 hard, from `pass_difficulty`


@dataclass(frozen=True)
class PassStats:
    """Passes of one player, one team or everyone, and the events each value comes from: counts,
    completion and length from `event_ids`, the difficulty from `completed_ids`. An average is
    None when there is nothing to average."""

    passes: int
    completed: int
    progressive: int
    completion: float | None  # completed / passes
    average_length_m: float | None
    average_completed_difficulty: float | None
    event_ids: tuple[str, ...]  # every pass
    completed_ids: tuple[str, ...]
    progressive_ids: tuple[str, ...]


def pass_difficulty(length_m: float, forward: float, opponent_m: float, zone: Zone) -> int:
    """0 (easy) to 100 (hard): the weighted sum of four parts, each from 0 to 1.

    Harder are longer passes (up to `LONGEST_M`), passes towards the goal attacked rather than
    back, an opponent closer to where the ball arrives (within `CLOSE_M`), and a target zone
    nearer to that goal. The rating never falls when one of them gets harder and the rest stay.
    """
    if not (length_m >= 0 and -1 <= forward <= 1 and opponent_m >= 0):
        raise ValueError(f"no pass is {length_m} m long, {forward} forward, {opponent_m} m free")
    zone = Zone(zone)
    return round(
        LENGTH_WEIGHT * min(length_m, LONGEST_M) / LONGEST_M
        + PRESSURE_WEIGHT * (CLOSE_M - min(opponent_m, CLOSE_M)) / CLOSE_M
        + DIRECTION_WEIGHT * (1 + forward) / 2
        + ZONE_WEIGHT * zone / Zone.PENALTY_AREA
    )


def pass_ratings(
    meta: MatchMeta, events: Iterable[Event], snapshots: Iterable[Snapshot]
) -> list[PassRating]:
    """A rating for every pass in `events` (a match's stream or any prefix of it), in order.

    Every `pass` event counts, restarts included. Only a complete pass has a receiver, so only
    it gets the nearest opponent and a difficulty. A failed pass is recorded where it ended, not
    where it was aimed, which would rate an interception as the pressure that beat it.

    `snapshots` must hold the instant every complete pass in `events` arrives, as a valid match
    does: a live caller passes the whole match's tracking, not tracking cut at the current
    clock. A pass still in flight at that clock is then rated from tracking up to a few seconds
    later; a caller that must not show it yet keeps the ratings whose `(period, arrival_ms)` is
    not after the current `(period, clock)`.
    """
    at = {(s.period, s.clock_ms): s for s in snapshots}
    return [_rate(meta, e, at) for e in events if e.type is EventType.PASS]


def pass_stats(
    ratings: Iterable[PassRating], team: str | None = None, player: str | None = None
) -> PassStats:
    """Counts and averages over the ratings of `team` and/or `player` (all when None)."""
    mine = [
        r
        for r in ratings
        if (team is None or r.team == team) and (player is None or r.player == player)
    ]
    done = [r for r in mine if r.complete]
    n, completed = len(mine), len(done)
    progressive = tuple(r.event_id for r in done if r.progressive)
    return PassStats(
        passes=n,
        completed=completed,
        progressive=len(progressive),
        completion=completed / n if n else None,
        average_length_m=math.fsum(r.length_m for r in mine) / n if n else None,
        average_completed_difficulty=(
            sum(r.difficulty for r in done) / completed if completed else None
        ),
        event_ids=tuple(r.event_id for r in mine),
        completed_ids=tuple(r.event_id for r in done),
        progressive_ids=progressive,
    )


def _rate(meta: MatchMeta, e: Event, at: dict[tuple[int, int], Snapshot]) -> PassRating:
    rightwards = attacking_goal_x(meta, e.team, e.period) == PITCH_LENGTH

    def frame(x: float, y: float) -> tuple[int, int]:
        return team_frame(x, y, rightwards)

    (x0, y0), (x1, y1) = frame(e.start.x, e.start.y), frame(e.end.x, e.end.y)
    length = math.hypot(x1 - x0, y1 - y0)
    complete = e.outcome is Outcome.COMPLETE
    end_zone = zone(x1, y1)
    forward = (x1 - x0) / length if length else 0.0
    opponent_m = difficulty = None
    if complete:
        arrival = at.get((e.period, e.clock_ms + e.duration_ms))
        if arrival is None:
            raise ValueError(f"{e.event_id}: no tracking at the instant the ball arrives")
        opponents = (frame(x, y) for pid, x, y in arrival.players if team_of(pid) != e.team)
        opponent_m = min(math.hypot(x - x1, y - y1) for x, y in opponents) / 100
        difficulty = pass_difficulty(length / 100, forward, opponent_m, end_zone)
    return PassRating(
        event_id=e.event_id,
        period=e.period,
        clock_ms=e.clock_ms,
        arrival_ms=e.clock_ms + e.duration_ms,
        team=e.team,
        player=e.player,
        complete=complete,
        length_m=length / 100,
        forward=forward,
        opponent_m=opponent_m,
        zone=end_zone,
        progressive=complete and e.restart is None and _progressive(x0, y0, x1, y1),
        difficulty=difficulty,
    )


def team_frame(x: float, y: float, rightwards: bool) -> tuple[int, int]:
    """Centimetres from a team's own goal line towards the goal it attacks, and across;
    `rightwards`: it attacks the goal at x = 105 (`attacking_goal_x`)."""
    x_cm, y_cm = round(x * 100), round(y * 100)
    return (x_cm if rightwards else _LENGTH - x_cm), y_cm


def in_opponent_half(x: int) -> bool:
    """A spot `x` centimetres into the team's frame is in the half it attacks; the halfway line
    counts as that half."""
    return 2 * x >= _LENGTH


def zone(x: int, y: int) -> Zone:
    """The zone of a spot in the team's frame, in centimetres."""
    box_x = _LENGTH - round(PENALTY_AREA_LENGTH * 100)
    if x >= box_x and abs(2 * y - _WIDTH) <= 2 * round(PENALTY_AREA_HALF_WIDTH * 100):
        return Zone.PENALTY_AREA
    return Zone(min(3 * x // _LENGTH, Zone.FINAL_THIRD))


def _progressive(x0: int, y0: int, x1: int, y1: int) -> bool:
    def to_goal(x: int, y: int) -> float:  # to the centre of the goal attacked
        return math.hypot(_LENGTH - x, y - _WIDTH / 2)

    halves = (in_opponent_half(x0), in_opponent_half(x1))
    needed = PROGRESS_M.get(halves)
    return needed is not None and to_goal(x0, y0) - to_goal(x1, y1) >= needed * 100

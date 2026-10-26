"""Speed and distance: the ball's speed from the events, each player's distance covered and top
speed from the 10 Hz tracking frames, and the triggers for overlay player tags.

Tracking values cite frame ids (`m7-f048346`) the way event values cite event ids.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from matchlens.events import SPECS, Event, EventType, TrackingFrame

# tag thresholds, from the distribution over seeds 0–49 (PROGRESS.md, Metrics)
HARD_SHOT_MS = 28.0  # the hardest fifth of all shots (p80 27.9 m/s), about 100 km/h
SPRINT_MS = 7.0  # 25.2 km/h, the usual sprint line (owner, 20 Oct); only a diving keeper gets there


@dataclass(frozen=True)
class BallSpeed:
    event_id: str
    period: int
    clock_ms: int  # when the ball is struck
    arrival_ms: int  # when it arrives
    type: EventType
    team: str
    player: str
    speed_ms: float


@dataclass(frozen=True)
class Movement:
    """How one player moved over a stretch of tracking."""

    player: str
    distance_m: float
    # fastest between two consecutive frames, and those two frames; 0.0 and () when the player
    # did not move, or from a single frame
    top_speed_ms: float
    top_speed_frames: tuple[str, ...]
    frame_ids: tuple[str, str]  # the first and the last frame counted


@dataclass(frozen=True)
class Tag:
    """A moment for an overlay player tag."""

    kind: str  # "sprint" or "hard_shot"
    player: str
    period: int
    clock_ms: int
    speed_ms: float
    source_ids: tuple[str, ...]  # a sprint's two frames, a shot's event


def ball_speeds(events: Iterable[Event]) -> list[BallSpeed]:
    """The ball's speed on every event in which it travels (pass, shot, clearance), in order.

    One formula, `Event.ball_speed()`: the straight line from start to end over the flight time,
    so the engine and the event never disagree. The event carries its end, so a ball still in
    the air at a live clock already has its speed; a caller that must not show it yet keeps the
    speeds whose `(period, arrival_ms)` is not after the current `(period, clock)`.
    """
    return [
        BallSpeed(
            e.event_id,
            e.period,
            e.clock_ms,
            e.clock_ms + e.duration_ms,
            e.type,
            e.team,
            e.player,
            e.ball_speed(),
        )
        for e in events
        if SPECS[e.type].travels
    ]


def movement(frames: Iterable[TrackingFrame]) -> dict[str, Movement]:
    """Distance covered and top speed of every player over `frames`, in time order: a match, a
    period, or any stretch or prefix of them.

    Consecutive frames of one period are joined by a straight line; the end of period 1 and the
    start of period 2 are not. One pass over the frames, so a whole match streams through.
    """
    seen: dict[str, list] = {}  # player: [distance, top speed, its frames, first, last frame]
    before = None
    for frame in frames:
        for p in frame.players:
            seen.setdefault(p.player, [0.0, 0.0, (), frame.frame_id, None])[4] = frame.frame_id
        if before is not None and before.period == frame.period:
            for player, metres, speed in _steps(before, frame):
                row = seen[player]
                row[0] += metres
                if speed > row[1]:
                    row[1], row[2] = speed, (before.frame_id, frame.frame_id)
        before = frame
    return {p: Movement(p, d, v, ids, (a, b)) for p, (d, v, ids, a, b) in seen.items()}


def upward_crossings(values: Sequence[float], threshold: float) -> list[int]:
    """Indices where `values` reach `threshold` from below. Nothing comes before the first
    value, so it counts when it is at or above the threshold."""
    return [
        i for i, v in enumerate(values) if v >= threshold and (i == 0 or values[i - 1] < threshold)
    ]


def sprint_tags(frames: Iterable[TrackingFrame], threshold: float = SPRINT_MS) -> list[Tag]:
    """A tag each time a player's speed between consecutive frames reaches `threshold` from
    below: the `upward_crossings` of each player's speeds, period by period, in time order.

    The first step of each period in `frames` counts when it is at or above the threshold, so
    `frames` starts where a period starts (a match, or a live prefix of it). For a window, take
    the tags of the prefix up to its end and keep those whose `(period, clock_ms)` falls in it.
    """
    tags = []
    speed_before: dict[str, float] = {}
    before = None
    for frame in frames:
        if before is None or before.period != frame.period:
            speed_before = {}
        else:
            for player, _, speed in _steps(before, frame):
                if speed >= threshold > speed_before.get(player, -math.inf):
                    ids = (before.frame_id, frame.frame_id)
                    tags.append(Tag("sprint", player, frame.period, frame.clock_ms, speed, ids))
                speed_before[player] = speed
        before = frame
    return tags


def hard_shot_tags(events: Iterable[Event], threshold: float = HARD_SHOT_MS) -> list[Tag]:
    """A tag for every shot whose ball speed is at or above `threshold`, in order."""
    return [
        Tag("hard_shot", e.player, e.period, e.clock_ms, e.ball_speed(), (e.event_id,))
        for e in events
        if e.type is EventType.SHOT and e.ball_speed() >= threshold
    ]


def _steps(before: TrackingFrame, after: TrackingFrame):
    """Each player's metres between two frames, and the speed that took."""
    ms = after.clock_ms - before.clock_ms
    if ms <= 0:
        return
    then = {p.player: p for p in before.players}
    for p in after.players:
        if (q := then.get(p.player)) is not None:
            metres = math.hypot(p.x - q.x, p.y - q.y)
            yield p.player, metres, metres * 1000 / ms

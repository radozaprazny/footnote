"""A whole match: metadata, the event stream, the tracking, and the invariants across them.

Generator v1 keeps `Snapshot`s, everyone's position at the instants that matter (every event,
every end of a ball flight), and `Match.frames()` interpolates the 10 Hz tracking between them.
Generator v2 keeps every frame, compactly (`Tracking`). `validate_match` checks what no single
event can: ids in emit order, time, lineups, goal ↔ shot links, restart positions, and that
tracking and events agree.
"""

import math
from array import array
from bisect import bisect_right
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from operator import sub

from matchlens.events import (
    FRAME_MS,
    MAX_BALL_SPEED,
    MAX_PERIOD_MS,
    PERIODS,
    PITCH_LENGTH,
    PITCH_WIDTH,
    Event,
    EventType,
    MatchMeta,
    Outcome,
    PlayerPosition,
    Point,
    Restart,
    TrackingFrame,
    make_event_id,
    make_frame_id,
    parse_event_id,
)

PLAYER_SPEED_LIMIT = 9.5  # m/s; elite sprints peak just under 10
GOAL_HALF_WIDTH = 3.66  # metres from the centre of the goal to a post
GOAL_AREA_LENGTH = 5.5
GOAL_AREA_HALF_WIDTH = 9.16
PENALTY_AREA_LENGTH = 16.5
PENALTY_AREA_HALF_WIDTH = 20.16
PENALTY_SPOT = 11.0
CENTRE = (PITCH_LENGTH / 2, PITCH_WIDTH / 2)
TOLERANCE = 0.011  # metres: coordinates are stored to the centimetre
SPEED_TOLERANCE = 0.05  # m/s: the same rounding, over the shortest snapshot gaps
# m a player's step between two snapshots may exceed his own top speed by: both positions are
# stored to the centimetre (generator v2, whose snapshots can lie 100 ms apart)
MOVE_TOLERANCE = 2 * TOLERANCE

Vec = tuple[float, float]


def attacking_goal_x(meta: MatchMeta, team: str, period: int) -> float:
    """x of the goal line `team` attacks in `period`: home attacks 105 in period 1, ends swap."""
    if team not in (meta.home, meta.away):
        raise ValueError(f"{meta.match_id}: {team} is not playing")
    if period not in PERIODS:
        raise ValueError(f"{meta.match_id}: period = {period!r} is not one of {PERIODS}")
    return PITCH_LENGTH if (team == meta.home) == (period == 1) else 0.0


@dataclass(frozen=True)
class Snapshot:
    """Everyone's position at one instant. Players keep the same order in every snapshot."""

    period: int
    clock_ms: int
    ball: Vec
    players: tuple[tuple[str, float, float], ...]


@dataclass(frozen=True)
class Tracking:
    """Every 10 Hz frame of a match, kept compactly (generator v2). For each period, the frames
    from clock 0 on, one every FRAME_MS: the ball's x and y, then each player's x and y in
    `players` order, in whole centimetres as signed 16-bit integers (the bytes of an
    `array('h')`): about 5 MB a match, where a `Snapshot` at every frame would take some 40 times
    that."""

    players: tuple[str, ...]
    periods: tuple[bytes, ...] = field(repr=False)  # period 1, then period 2

    @property
    def width(self) -> int:
        """Values in a frame: the ball's two and two for each player."""
        return 2 + 2 * len(self.players)

    def values(self, period: int) -> array:
        """The period's frames one after the other, in centimetres."""
        return array("h", self.periods[period - 1])

    def count(self, period: int) -> int:
        """The period's number of frames."""
        return len(self.periods[period - 1]) // (2 * self.width)

    def ends(self) -> dict[int, int]:
        """The clock of each period's last frame."""
        return {p: (self.count(p) - 1) * FRAME_MS for p in PERIODS if self.count(p)}

    def holds(self, period: int, clock_ms: int) -> bool:
        """Whether there is a frame at (period, clock_ms)."""
        return (
            period in PERIODS
            and type(clock_ms) is int
            and clock_ms % FRAME_MS == 0
            and 0 <= clock_ms < self.count(period) * FRAME_MS
        )

    def snapshot(self, period: int, clock_ms: int) -> Snapshot:
        """The frame at (period, clock_ms), which `holds`, as a `Snapshot`."""
        v = self._row(period, clock_ms)
        players = tuple(
            (pid, x / 100, y / 100)
            for pid, x, y in zip(self.players, v[2::2], v[3::2], strict=True)
        )
        return Snapshot(period, clock_ms, (v[0] / 100, v[1] / 100), players)

    def frames(
        self, match_id: str, period: int, first: int, every_ms: int
    ) -> Iterator[TrackingFrame]:
        """The period's frames from clock `first` on, every `every_ms`."""
        values, w = memoryview(self.periods[period - 1]).cast("h"), self.width
        for clock in range(first, self.count(period) * FRAME_MS, every_ms):
            i = clock // FRAME_MS * w
            yield self._frame(match_id, period, clock, values[i : i + w].tolist())

    def frame(self, match_id: str, period: int, clock_ms: int) -> TrackingFrame:
        """The frame at (period, clock_ms), which `holds`."""
        return self._frame(match_id, period, clock_ms, self._row(period, clock_ms))

    def _row(self, period: int, clock_ms: int) -> list[int]:
        i = clock_ms // FRAME_MS * self.width
        return memoryview(self.periods[period - 1]).cast("h")[i : i + self.width].tolist()

    def _frame(self, match_id: str, period: int, clock: int, v: list[int]) -> TrackingFrame:
        return TrackingFrame(
            frame_id=make_frame_id(match_id, period, clock),
            period=period,
            clock_ms=clock,
            players=tuple(
                PlayerPosition(pid, x / 100, y / 100)
                for pid, x, y in zip(self.players, v[2::2], v[3::2], strict=True)
            ),
            ball=Point(v[0] / 100, v[1] / 100),
        )


@dataclass(frozen=True)
class Match:
    meta: MatchMeta
    events: tuple[Event, ...]
    snapshots: tuple[Snapshot, ...]
    # generator v2: every frame, in place of the snapshots (left empty)
    tracking: Tracking | None = field(default=None, repr=False)

    def score(self) -> tuple[int, int]:
        """Home goals, away goals: the count of goal events."""
        teams = [e.team for e in self.events if e.type is EventType.GOAL]
        return teams.count(self.meta.home), teams.count(self.meta.away)

    def frames(
        self, every_ms: int = FRAME_MS, start: tuple[int, int] = (1, 0)
    ) -> Iterator[TrackingFrame]:
        """Tracking at 10 Hz: the frames kept (generator v2), or interpolated between consecutive
        snapshots of each period.

        `every_ms` (a multiple of FRAME_MS) keeps only the frames whose clock is a multiple of
        it; `start` (period, clock_ms) skips the frames before it without computing them.
        Assumes a match that passes `validate_match` (snapshots in order, from 0).
        """
        if every_ms <= 0 or every_ms % FRAME_MS:
            raise ValueError(f"every_ms {every_ms} is not a positive multiple of {FRAME_MS}")
        if self.tracking is not None:
            for period in PERIODS:
                if period >= start[0]:
                    first = -(-start[1] // every_ms) * every_ms if period == start[0] else 0
                    yield from self.tracking.frames(self.meta.match_id, period, first, every_ms)
            return
        for period in PERIODS:
            snaps = [s for s in self.snapshots if s.period == period]
            if period < start[0] or not snaps:
                continue
            first = -(-start[1] // every_ms) * every_ms if period == start[0] else 0
            i = max(bisect_right([s.clock_ms for s in snaps], first) - 1, 0)
            for clock in range(first, snaps[-1].clock_ms + 1, every_ms):
                while i + 1 < len(snaps) and snaps[i + 1].clock_ms <= clock:
                    i += 1
                yield self._frame(period, clock, snaps, i)

    def frame_at(self, period: int, clock_ms: int) -> TrackingFrame:
        """The frame `frames()` yields at (period, clock_ms), without the frames before it."""
        if self.tracking is not None:
            if not self.tracking.holds(period, clock_ms):
                raise ValueError(
                    f"{self.meta.match_id}: no frame at period {period}, {clock_ms} ms"
                )
            return self.tracking.frame(self.meta.match_id, period, clock_ms)
        snaps = [s for s in self.snapshots if s.period == period]
        if not snaps or clock_ms % FRAME_MS or not 0 <= clock_ms <= snaps[-1].clock_ms:
            raise ValueError(f"{self.meta.match_id}: no frame at period {period}, {clock_ms} ms")
        before = bisect_right([s.clock_ms for s in snaps], clock_ms) - 1
        return self._frame(period, clock_ms, snaps, before)

    def snapshots_at(self, instants: Iterable[tuple[int, int]]) -> tuple[Snapshot, ...]:
        """Everyone's position at each of `instants` (period, clock_ms) the tracking holds, in
        time order: the snapshots kept there, or read from the frames (generator v2)."""
        wanted = set(instants)
        if self.tracking is None:
            return tuple(s for s in self.snapshots if (s.period, s.clock_ms) in wanted)
        held = sorted(i for i in wanted if self.tracking.holds(*i))
        return tuple(self.tracking.snapshot(period, clock) for period, clock in held)

    def _frame(self, period: int, clock: int, snaps: list[Snapshot], i: int) -> TrackingFrame:
        """The frame at `clock`, between snapshot `i` (at or before it) and the next."""
        a = snaps[i]
        b = snaps[i + 1] if i + 1 < len(snaps) else a
        span = b.clock_ms - a.clock_ms
        f = (clock - a.clock_ms) / span if span else 0.0
        return TrackingFrame(
            frame_id=make_frame_id(self.meta.match_id, period, clock),
            period=period,
            clock_ms=clock,
            players=tuple(
                PlayerPosition(pa[0], _lerp(pa[1], pb[1], f), _lerp(pa[2], pb[2], f))
                for pa, pb in zip(a.players, b.players, strict=True)
            ),
            ball=Point(_lerp(a.ball[0], b.ball[0], f), _lerp(a.ball[1], b.ball[1], f)),
        )


def validate_match(match: Match, top_speeds: Mapping[str, float] | None = None) -> None:
    """Raise ValueError naming the first broken invariant across events, lineups and tracking.

    Every player keeps PLAYER_SPEED_LIMIT (generator v1); given `top_speeds` (generator v2), each
    keeps his own top speed instead, to the centimetre's rounding of his two positions: between
    consecutive snapshots, or in every 100 ms step of a match that keeps its `Tracking`."""
    meta, events = match.meta, match.events
    if not events:
        raise ValueError(f"{meta.match_id}: no events")
    lineups = {meta.home: set(meta.home_lineup), meta.away: set(meta.away_lineup)}
    _check_order_and_lineups(meta, events, lineups)
    for seq, e in enumerate(events):
        _check_links(events, seq, e)
        if e.team is not None:
            _check_positions(meta, e)
    everyone = lineups[meta.home] | lineups[meta.away]
    if top_speeds is not None and (missing := sorted(everyone - set(top_speeds))):
        raise ValueError(f"{meta.match_id}: no top speed for {', '.join(missing)}")
    if match.tracking is None:
        ends, snapshot_at = _check_snapshots(match, everyone, top_speeds)
    else:
        ends, snapshot_at = _check_tracking(match, everyone, top_speeds)
    _check_events_in_tracking(match, ends, snapshot_at)


def _check_order_and_lineups(meta: MatchMeta, events: tuple[Event, ...], lineups: dict) -> None:
    last = (1, 0)
    ended: set[int] = set()
    for seq, e in enumerate(events):
        expected = make_event_id(meta.match_id, seq)
        if e.event_id != expected:
            raise ValueError(f"{e.event_id}: event number {seq} should have id {expected}")
        if (e.period, e.clock_ms) < last:
            raise ValueError(f"{e.event_id}: time goes backwards")
        last = (e.period, e.clock_ms)
        if e.period in ended:
            raise ValueError(f"{e.event_id}: after the end of period {e.period}")
        if e.type is EventType.PERIOD_END:
            ended.add(e.period)
        if e.team is not None:
            if e.team not in lineups:
                raise ValueError(f"{e.event_id}: team {e.team} is not playing")
            for who in (e.player, e.recipient):
                if who is not None and who not in lineups[e.team]:
                    raise ValueError(f"{e.event_id}: {who} is not in the {e.team} lineup")
    if ended != set(PERIODS) or events[-1].type is not EventType.PERIOD_END:
        raise ValueError(f"{meta.match_id}: each period must end with period_end, last of all")


def _check_links(events: tuple[Event, ...], seq: int, e: Event) -> None:
    """A goal follows its shot; a save follows its shot; and the other way round."""
    following = events[seq + 1] if seq + 1 < len(events) else None
    if e.type is EventType.SHOT and e.outcome in (Outcome.GOAL, Outcome.SAVED):
        wanted = EventType.GOAL if e.outcome is Outcome.GOAL else EventType.SAVE
        if following is None or following.type is not wanted or following.related != e.event_id:
            raise ValueError(f"{e.event_id}: a {e.outcome} shot must be followed by its {wanted}")
    if e.type in (EventType.GOAL, EventType.SAVE):
        shot_seq = parse_event_id(e.related)[1]
        shot = events[shot_seq]
        if shot_seq != seq - 1 or shot.type is not EventType.SHOT:
            raise ValueError(f"{e.event_id}: {e.type} must directly follow its shot")
        if e.type is EventType.GOAL and (
            shot.outcome is not Outcome.GOAL or (shot.team, shot.player) != (e.team, e.player)
        ):
            raise ValueError(f"{e.event_id}: goal must follow a goal shot by the same player")
        if e.type is EventType.SAVE and (shot.outcome is not Outcome.SAVED or shot.team == e.team):
            raise ValueError(f"{e.event_id}: save must follow a saved shot by the other team")


def _check_positions(meta: MatchMeta, e: Event) -> None:
    """Goals end between the posts; restarts are taken from where the rules put them."""
    goal_x = attacking_goal_x(meta, e.team, e.period)
    own_x = PITCH_LENGTH - goal_x
    inwards = 1.0 if goal_x == 0.0 else -1.0  # from the attacked goal line into the pitch
    s = e.start
    scored = e.type is EventType.SHOT and e.outcome is Outcome.GOAL
    if scored and not (_near(e.end.x, goal_x) and abs(e.end.y - CENTRE[1]) <= GOAL_HALF_WIDTH):
        raise ValueError(f"{e.event_id}: a goal must end on the goal line between the posts")
    on_a_touchline = _near(s.y, 0.0) or _near(s.y, PITCH_WIDTH)
    rules = {
        Restart.KICK_OFF: lambda: _near(s.x, CENTRE[0]) and _near(s.y, CENTRE[1]),
        Restart.CORNER: lambda: _near(s.x, goal_x) and on_a_touchline,
        Restart.PENALTY: lambda: (
            _near(s.x, goal_x + inwards * PENALTY_SPOT) and _near(s.y, CENTRE[1])
        ),
        Restart.THROW_IN: lambda: on_a_touchline,
        Restart.GOAL_KICK: lambda: (
            abs(s.x - own_x) <= GOAL_AREA_LENGTH + TOLERANCE
            and abs(s.y - CENTRE[1]) <= GOAL_AREA_HALF_WIDTH + TOLERANCE
        ),
        Restart.FREE_KICK: lambda: True,
    }
    if e.restart is not None and not rules[e.restart]():
        raise ValueError(f"{e.event_id}: a {e.restart} is not taken from ({s.x}, {s.y})")


def _check_snapshots(match: Match, everyone: set, top_speeds: Mapping | None) -> tuple:
    """The snapshots' own invariants; each period's last clock and the snapshot at an instant."""
    meta, snaps = match.meta, match.snapshots
    at: dict[tuple[int, int], Snapshot] = {}
    previous: dict[int, Snapshot] = {}
    for s in snaps:
        what = f"{meta.match_id} snapshot {s.period!r}/{s.clock_ms!r}"
        try:
            if type(s.period) is not int or s.period not in PERIODS:
                raise ValueError(f"period = {s.period!r} is not one of {PERIODS}")
            if type(s.clock_ms) is not int or not 0 <= s.clock_ms <= MAX_PERIOD_MS:
                raise ValueError(f"clock_ms = {s.clock_ms!r} is not an int in 0-{MAX_PERIOD_MS}")
            if any(len(p) != 3 for p in s.players):
                raise ValueError("every player entry must be (id, x, y)")
            ids = [p[0] for p in s.players]
            if len(ids) != len(everyone) or set(ids) != everyone:
                raise ValueError("players are not the two lineups")
            Point(*s.ball)
            for p in s.players:
                Point(p[1], p[2])
        except (ValueError, TypeError, IndexError) as err:
            raise ValueError(f"{what}: {err}") from None
        if (before := previous.get(s.period)) is None:
            if s.clock_ms != 0:
                raise ValueError(f"{what}: tracking of period {s.period} must start at 0")
        else:
            if s.clock_ms <= before.clock_ms:
                raise ValueError(f"{what}: not after the previous snapshot of the period")
            if before.players and ids != [p[0] for p in before.players]:
                raise ValueError(f"{what}: player order changed")
            dt = (s.clock_ms - before.clock_ms) / 1000
            for (pid, x, y), (_, x0, y0) in zip(s.players, before.players, strict=True):
                moved = math.hypot(x - x0, y - y0)
                if top_speeds is None:
                    if moved / dt > PLAYER_SPEED_LIMIT + SPEED_TOLERANCE:
                        raise ValueError(
                            f"{what}: {pid} moved faster than {PLAYER_SPEED_LIMIT} m/s"
                        )
                elif moved > top_speeds[pid] * dt + MOVE_TOLERANCE:
                    raise ValueError(f"{what}: {pid} moved faster than his {top_speeds[pid]} m/s")
            if math.dist(s.ball, before.ball) / dt > MAX_BALL_SPEED + SPEED_TOLERANCE:
                raise ValueError(f"{what}: the ball moved faster than {MAX_BALL_SPEED} m/s")
        previous[s.period] = s
        at[(s.period, s.clock_ms)] = s
    ends = {period: s.clock_ms for period, s in previous.items()}
    return ends, lambda period, clock_ms: at.get((period, clock_ms))


def _check_tracking(match: Match, everyone: set, top_speeds: Mapping | None) -> tuple:
    """The kept frames' own invariants (generator v2): every player and the ball on the pitch in
    every frame, and within his speed in every 100 ms step; each period's last clock and the
    snapshot at an instant."""
    meta, tracking = match.meta, match.tracking
    what = f"{meta.match_id} tracking"
    if match.snapshots:
        raise ValueError(f"{what}: a match keeps snapshots or tracking, not both")
    if len(tracking.players) != len(everyone) or set(tracking.players) != everyone:
        raise ValueError(f"{what}: players are not the two lineups")
    if len(tracking.periods) != len(PERIODS):
        raise ValueError(f"{meta.match_id}: tracking must cover both periods")
    dt = FRAME_MS / 1000
    w, most = tracking.width, MAX_PERIOD_MS // FRAME_MS + 1
    x_cm, y_cm = PITCH_LENGTH * 100, PITCH_WIDTH * 100
    for period in PERIODS:
        size = len(tracking.periods[period - 1])
        if size % (2 * w) or not 0 < size // (2 * w) <= most:
            raise ValueError(f"{what}: period {period} is not 1-{most} whole frames")
        values = tracking.values(period)
        for k, who in enumerate(("the ball", *tracking.players)):
            xs, ys = values[2 * k :: w], values[2 * k + 1 :: w]
            if min(xs) < 0 or max(xs) > x_cm or min(ys) < 0 or max(ys) > y_cm:
                off = next(
                    i
                    for i, (x, y) in enumerate(zip(xs, ys, strict=True))
                    if not (0 <= x <= x_cm and 0 <= y <= y_cm)
                )
                raise ValueError(
                    f"{meta.match_id} frame {period}/{off * FRAME_MS}: {who} is off the pitch"
                )
            # each 100 ms step's length, in the frames' centimetres
            steps = list(map(math.hypot, map(sub, xs[1:], xs), map(sub, ys[1:], ys)))
            if who == "the ball":
                bound, limit = (MAX_BALL_SPEED + SPEED_TOLERANCE) * dt, f"{MAX_BALL_SPEED} m/s"
            elif top_speeds is None:
                bound = (PLAYER_SPEED_LIMIT + SPEED_TOLERANCE) * dt
                limit = f"{PLAYER_SPEED_LIMIT} m/s"
            else:
                bound, limit = top_speeds[who] * dt + MOVE_TOLERANCE, f"his {top_speeds[who]} m/s"
            if steps and max(steps) / 100 > bound:  # metres a step
                clock = (next(i for i, cm in enumerate(steps) if cm / 100 > bound) + 1) * FRAME_MS
                raise ValueError(
                    f"{meta.match_id} frame {period}/{clock}: {who} moved faster than {limit}"
                )
    return (
        tracking.ends(),
        lambda period, clock_ms: (
            tracking.snapshot(period, clock_ms) if tracking.holds(period, clock_ms) else None
        ),
    )


def _check_events_in_tracking(match: Match, ends: dict[int, int], snapshot_at) -> None:
    """Tracking covers both periods, ends at each period_end, and holds every event: the ball
    and its player where the event starts, and where it ends."""
    meta = match.meta
    if set(ends) != set(PERIODS):
        raise ValueError(f"{meta.match_id}: tracking must cover both periods")
    for e in match.events:
        if e.type is EventType.PERIOD_END and ends[e.period] != e.clock_ms:
            raise ValueError(
                f"{meta.match_id}: tracking of period {e.period} must end at period_end"
            )
    for e in match.events:
        if e.team is None:
            continue
        # a goal is recorded where the ball crossed the line; the scorer is back at the shot
        scorer = None if e.type is EventType.GOAL else e.player
        _check_event_in_tracking(snapshot_at, e, e.clock_ms, e.start, scorer)
        if e.end is not None:
            _check_event_in_tracking(snapshot_at, e, e.clock_ms + e.duration_ms, e.end, e.recipient)


def _check_event_in_tracking(snapshot_at, e: Event, clock_ms: int, where: Point, who: str | None):
    s = snapshot_at(e.period, clock_ms)
    if s is None:
        raise ValueError(f"{e.event_id}: no snapshot at {e.period}/{clock_ms}")
    if not (_near(s.ball[0], where.x) and _near(s.ball[1], where.y)):
        raise ValueError(f"{e.event_id}: the ball is not at ({where.x}, {where.y}) in the tracking")
    if who is not None:
        x, y = next((p[1], p[2]) for p in s.players if p[0] == who)
        if not (_near(x, where.x) and _near(y, where.y)):
            raise ValueError(f"{e.event_id}: {who} is not at ({where.x}, {where.y}) in tracking")


def _near(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


def _lerp(a: float, b: float, f: float) -> float:
    return round(a + (b - a) * f, 2)

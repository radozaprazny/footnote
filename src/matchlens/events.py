"""Match event schema: the contract between generator, stream, stats engine and overlay.

Coordinates are metres on a 105 x 68 m pitch, fixed to the ground: x runs along the length
(0 and 105 are the goal lines), y across the width (0 and 68 are the touchlines). Convention: in
period 1 the home team attacks towards x = 105 and the away team towards x = 0; in period 2 they
swap ends. The clock restarts at 0 in each period; `display_clock` renders the broadcast form.

Restarts (kick-off, throw-in, corner, ...) are passes or shots with a `restart` qualifier, not
event types of their own, so every event in which the ball travels has start, end, duration and
outcome. A `goal` event follows the shot it comes from and points at it through `related`, as a
`save` does. Possession is not stored: `matchlens.stats.possession` derives it from the event
sequence. A `recovery` marks the player who picks up a loose ball, the one change of possession
that no other event shows.
This version has no cards, substitutions or own goals: a tracking frame always holds 11 + 11
players, and the generator clamps positions to the pitch.

Every object validates itself on construction and round-trips through `to_dict` / `from_dict`
as plain JSON types.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, fields
from enum import StrEnum
from functools import lru_cache
from typing import Any, Self

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0
PERIODS = (1, 2)
HALF_MS = 45 * 60 * 1000
MAX_PERIOD_MS = 60 * 60 * 1000  # 45 minutes plus generous stoppage time
MAX_TRAVEL_MS = 10_000  # longest a pass, shot or clearance is on its way
MAX_BALL_SPEED = 50.0  # m/s, about 180 km/h
FRAME_MS = 100  # tracking at 10 Hz
FRAMES_PER_PERIOD = MAX_PERIOD_MS // FRAME_MS + 1  # clock 0 to MAX_PERIOD_MS inclusive
PLAYERS_PER_TEAM = 11
MAX_SEQ = 99_999
MAX_SEED = 2**63 - 1

_ID = re.compile(r"[a-z0-9]+")  # match ids and club ids
_PLAYER_ID = re.compile(r"([a-z0-9]+)-[a-z0-9]+")
_EVENT_ID = re.compile(r"([a-z0-9]+)-e([0-9]{5})")
_FRAME_ID = re.compile(r"([a-z0-9]+)-f([0-9]{6})")


class EventType(StrEnum):
    PASS = "pass"
    SHOT = "shot"
    CLEARANCE = "clearance"
    TACKLE = "tackle"
    INTERCEPTION = "interception"
    RECOVERY = "recovery"
    PRESSURE = "pressure"
    FOUL = "foul"
    SAVE = "save"
    GOAL = "goal"
    PERIOD_END = "period_end"


class Outcome(StrEnum):
    # pass, clearance
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    OUT = "out"
    # shot
    GOAL = "goal"
    SAVED = "saved"
    BLOCKED = "blocked"
    OFF_TARGET = "off_target"
    WOODWORK = "woodwork"
    # tackle
    WON = "won"
    LOST = "lost"
    # pressure
    REGAIN = "regain"
    RESISTED = "resisted"


class Restart(StrEnum):
    KICK_OFF = "kick_off"
    THROW_IN = "throw_in"
    GOAL_KICK = "goal_kick"
    CORNER = "corner"
    FREE_KICK = "free_kick"
    PENALTY = "penalty"


@dataclass(frozen=True)
class Spec:
    """What an event type carries."""

    actor: bool = True  # team, player and start are required
    travels: bool = False  # the ball moves: end and duration_ms are required
    outcomes: frozenset[Outcome] = frozenset()  # non-empty: an outcome from this set is required
    restarts: frozenset[Restart] = frozenset()  # restart qualifiers this type may carry
    recipient: bool = False  # a recipient is required when the outcome is complete
    related: bool = False  # the event id of the shot it comes from is required


_BALL_OUTCOMES = frozenset({Outcome.COMPLETE, Outcome.INCOMPLETE, Outcome.OUT})
_SHOT_OUTCOMES = frozenset(
    {Outcome.GOAL, Outcome.SAVED, Outcome.BLOCKED, Outcome.OFF_TARGET, Outcome.WOODWORK}
)
_ALL_RESTARTS = frozenset(Restart)
_SHOT_RESTARTS = _ALL_RESTARTS - {Restart.THROW_IN}  # no goal straight from a throw-in
SPECS: dict[EventType, Spec] = {
    EventType.PASS: Spec(
        travels=True, outcomes=_BALL_OUTCOMES, restarts=_ALL_RESTARTS, recipient=True
    ),
    EventType.SHOT: Spec(travels=True, outcomes=_SHOT_OUTCOMES, restarts=_SHOT_RESTARTS),
    EventType.CLEARANCE: Spec(travels=True, outcomes=_BALL_OUTCOMES, recipient=True),
    EventType.TACKLE: Spec(outcomes=frozenset({Outcome.WON, Outcome.LOST})),
    EventType.INTERCEPTION: Spec(),
    EventType.RECOVERY: Spec(),
    EventType.PRESSURE: Spec(outcomes=frozenset({Outcome.REGAIN, Outcome.RESISTED})),
    EventType.FOUL: Spec(),
    EventType.SAVE: Spec(related=True),
    EventType.GOAL: Spec(related=True),
    EventType.PERIOD_END: Spec(actor=False),
}


def make_event_id(match_id: str, seq: int) -> str:
    """`m7-e00042`: stable id of event number `seq` of match `match_id`."""
    _check_match_id(match_id)
    _check_int(seq, 0, MAX_SEQ, "seq")
    return f"{match_id}-e{seq:05d}"


def parse_event_id(event_id: str) -> tuple[str, int]:
    """Inverse of `make_event_id`; ValueError if the id is not of that form."""
    m = _EVENT_ID.fullmatch(event_id) if isinstance(event_id, str) else None
    if m is None:
        raise ValueError(f"{event_id!r} is not an event id like m7-e00042")
    return m[1], int(m[2])


def frame_number(period: int, clock_ms: int) -> int:
    """Tracking frames are numbered by time: 0 at the first kick-off, 10 per second.

    Period 2 starts at FRAMES_PER_PERIOD, so numbers jump at half time unless the first half ran
    to the limit; within a period they are consecutive.
    """
    return _frame_number(period, clock_ms, "frame")


def make_frame_id(match_id: str, period: int, clock_ms: int) -> str:
    """`m7-f000123`: stable id of the tracking frame of `match_id` at (period, clock_ms)."""
    _check_match_id(match_id)
    return f"{match_id}-f{frame_number(period, clock_ms):06d}"


def parse_frame_id(frame_id: str) -> tuple[str, int]:
    """Match id and frame number; ValueError if the id is not of the `make_frame_id` form."""
    m = _FRAME_ID.fullmatch(frame_id) if isinstance(frame_id, str) else None
    if m is None:
        raise ValueError(f"{frame_id!r} is not a frame id like m7-f000123")
    return m[1], int(m[2])


def frame_time(frame_id: str) -> tuple[str, int, int]:
    """Match id, period and clock_ms of a frame id: the inverse of `make_frame_id`."""
    match_id, number = parse_frame_id(frame_id)
    period, step = divmod(number, FRAMES_PER_PERIOD)
    if period + 1 not in PERIODS:
        raise ValueError(f"{frame_id}: frame number {number} is past the last period")
    return match_id, period + 1, step * FRAME_MS


def team_of(player_id: str) -> str:
    """Club id of a player id (`cor-p07` -> `cor`)."""
    if not isinstance(player_id, str):
        raise ValueError(f"{player_id!r} is not a player id like cor-p07")
    return _club_of(player_id)


@lru_cache(maxsize=1024)  # every tracking frame asks for its 22 players twice
def _club_of(player_id: str) -> str:
    m = _PLAYER_ID.fullmatch(player_id)
    if m is None:
        raise ValueError(f"{player_id!r} is not a player id like cor-p07")
    return m[1]


def display_clock(period: int, clock_ms: int) -> str:
    """Broadcast clock: `12:34`, `45+2:13` in first-half stoppage time, `67:23`, `90+3:01`."""
    _check_period_clock(period, clock_ms, "clock")
    minutes, seconds = divmod(clock_ms // 1000, 60)
    half = HALF_MS // 60_000
    if minutes < half:
        return f"{half * (period - 1) + minutes:02d}:{seconds:02d}"
    return f"{half * period}+{minutes - half}:{seconds:02d}"


@dataclass(frozen=True)
class Point:
    """A spot on the pitch, metres."""

    x: float
    y: float

    def __post_init__(self) -> None:
        _init_coordinates(self)

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True)
class Event:
    event_id: str
    period: int
    clock_ms: int  # since the kick-off of this period
    type: EventType
    team: str | None = None
    player: str | None = None
    start: Point | None = None
    end: Point | None = None
    outcome: Outcome | None = None
    restart: Restart | None = None
    duration_ms: int | None = None  # how long the ball travelled: pass, shot, clearance
    recipient: str | None = None  # who received a complete pass or clearance
    related: str | None = None  # goal, save: the event id of the shot

    def __post_init__(self) -> None:
        match_id, seq = parse_event_id(self.event_id)
        what = self.event_id
        _check_period_clock(self.period, self.clock_ms, what)
        if self.type is None:
            raise ValueError(f"{what}: type is required")
        object.__setattr__(self, "type", _enum(EventType, self.type, what))
        object.__setattr__(self, "outcome", _enum(Outcome, self.outcome, what))
        object.__setattr__(self, "restart", _enum(Restart, self.restart, what))
        spec = SPECS[self.type]
        if spec.actor:
            if self.team is None or self.player is None or self.start is None:
                raise ValueError(f"{what}: {self.type} needs team, player and start")
            _check_actor(self.team, self.player, what)
        elif self.team is not None or self.player is not None or self.start is not None:
            raise ValueError(f"{what}: {self.type} must not have team, player or start")
        for name in ("start", "end"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Point):
                raise ValueError(f"{what}: {name} must be a Point")
        if spec.travels:
            if self.end is None or self.duration_ms is None:
                raise ValueError(f"{what}: {self.type} needs end and duration_ms")
            _check_int(self.duration_ms, 1, MAX_TRAVEL_MS, f"{what}: duration_ms")
            if self.clock_ms + self.duration_ms > MAX_PERIOD_MS:
                raise ValueError(f"{what}: the ball is still travelling after the period limit")
            speed = self.ball_speed()
            if speed > MAX_BALL_SPEED:
                raise ValueError(f"{what}: ball speed {speed:.1f} m/s is over {MAX_BALL_SPEED:g}")
        elif self.end is not None or self.duration_ms is not None:
            raise ValueError(f"{what}: {self.type} must not have end or duration_ms")
        if spec.outcomes:
            if self.outcome not in spec.outcomes:
                allowed = ", ".join(sorted(spec.outcomes))
                raise ValueError(f"{what}: {self.type} outcome must be one of {allowed}")
        elif self.outcome is not None:
            raise ValueError(f"{what}: {self.type} must not have an outcome")
        if self.restart is not None and self.restart not in spec.restarts:
            raise ValueError(f"{what}: {self.type} cannot be a {self.restart} restart")
        if spec.recipient and self.outcome is Outcome.COMPLETE:
            if self.recipient is None:
                raise ValueError(f"{what}: a complete {self.type} needs a recipient")
            _check_actor(self.team, self.recipient, f"{what}: recipient")
            if self.recipient == self.player:
                raise ValueError(f"{what}: recipient {self.recipient} is the player")
        elif self.recipient is not None:
            raise ValueError(f"{what}: only a complete pass or clearance has a recipient")
        if spec.related:
            if self.related is None:
                raise ValueError(f"{what}: {self.type} needs related, the event id of its shot")
            related_match, related_seq = parse_event_id(self.related)
            if related_match != match_id or related_seq >= seq:
                raise ValueError(f"{what}: related {self.related} is not an earlier event here")
        elif self.related is not None:
            raise ValueError(f"{what}: {self.type} must not have related")

    def ball_speed(self) -> float:
        """Metres per second over the ball's path; only for pass, shot and clearance."""
        if self.end is None:
            raise ValueError(f"{self.event_id}: {self.type} has no ball path")
        metres = math.dist((self.start.x, self.start.y), (self.end.x, self.end.y))
        return metres * 1000 / self.duration_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "period": self.period,
            "clock_ms": self.clock_ms,
            "type": self.type.value,
            "team": self.team,
            "player": self.player,
            "start": None if self.start is None else self.start.to_dict(),
            "end": None if self.end is None else self.end.to_dict(),
            "outcome": None if self.outcome is None else self.outcome.value,
            "restart": None if self.restart is None else self.restart.value,
            "duration_ms": self.duration_ms,
            "recipient": self.recipient,
            "related": self.related,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        what = _check_keys(data, cls, "event_id")
        points = {name: _point(data[name], f"{what}: {name}") for name in ("start", "end")}
        return cls(**(data | points))


@dataclass(frozen=True)
class PlayerPosition:
    player: str
    x: float
    y: float

    def __post_init__(self) -> None:
        team_of(self.player)
        _init_coordinates(self, self.player)

    def to_dict(self) -> dict[str, Any]:
        return {"player": self.player, "x": self.x, "y": self.y}


@dataclass(frozen=True)
class TrackingFrame:
    """Where everyone is, 10 times a second: 22 players and the ball."""

    frame_id: str
    period: int
    clock_ms: int
    players: tuple[PlayerPosition, ...]
    ball: Point

    def __post_init__(self) -> None:
        _, number = parse_frame_id(self.frame_id)
        what = self.frame_id
        if number != _frame_number(self.period, self.clock_ms, what):
            raise ValueError(f"{what}: frame number {number} does not match the period and clock")
        if not isinstance(self.players, list | tuple):
            raise ValueError(f"{what}: players must be a list")
        players = tuple(self.players)
        object.__setattr__(self, "players", players)
        if not all(isinstance(p, PlayerPosition) for p in players):
            raise ValueError(f"{what}: players must be PlayerPosition objects")
        if len(players) != 2 * PLAYERS_PER_TEAM:
            raise ValueError(f"{what}: {len(players)} players, expected {2 * PLAYERS_PER_TEAM}")
        names = [p.player for p in players]
        if len(set(names)) != len(names):
            _require_unique(f"{what}: duplicate player", names)
        per_team = Counter(team_of(name) for name in names)
        if len(per_team) != 2:
            raise ValueError(f"{what}: {len(per_team)} teams on the pitch, expected 2")
        for team, n in sorted(per_team.items()):
            if n != PLAYERS_PER_TEAM:
                raise ValueError(f"{what}: {team} has {n} players, expected {PLAYERS_PER_TEAM}")
        if not isinstance(self.ball, Point):
            raise ValueError(f"{what}: ball must be a Point")

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "period": self.period,
            "clock_ms": self.clock_ms,
            "players": [p.to_dict() for p in self.players],
            "ball": self.ball.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        what = _check_keys(data, cls, "frame_id")
        if not isinstance(data["players"], list):
            raise ValueError(f"{what}: players must be a list")
        players = tuple(_player_position(p, what) for p in data["players"])
        ball = _point(data["ball"], f"{what}: ball")
        return cls(**(data | {"players": players, "ball": ball}))


@dataclass(frozen=True)
class MatchMeta:
    """Who plays whom, the starting elevens, and the seed the match was generated from."""

    match_id: str
    home: str
    away: str
    home_lineup: tuple[str, ...]
    away_lineup: tuple[str, ...]
    seed: int

    def __post_init__(self) -> None:
        _check_match_id(self.match_id)
        what = self.match_id
        for team in (self.home, self.away):
            _check_club_id(team, what)
        if self.home == self.away:
            raise ValueError(f"{what}: home and away are both {self.home}")
        for name, team in (("home_lineup", self.home), ("away_lineup", self.away)):
            if not isinstance(getattr(self, name), list | tuple):
                raise ValueError(f"{what}: {name} must be a list")
            lineup = tuple(getattr(self, name))
            object.__setattr__(self, name, lineup)
            if len(lineup) != PLAYERS_PER_TEAM:
                raise ValueError(f"{what}: {name} has {len(lineup)} players, expected 11")
            for player in lineup:
                _check_actor(team, player, f"{what}: {name}")
            _require_unique(f"{what}: duplicate player in {name}", lineup)
        _check_int(self.seed, 0, MAX_SEED, f"{what}: seed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "home": self.home,
            "away": self.away,
            "home_lineup": list(self.home_lineup),
            "away_lineup": list(self.away_lineup),
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        _check_keys(data, cls, "match_id")
        return cls(**data)


def _enum[E: StrEnum](kind: type[E], value: Any, what: str) -> E | None:
    """Coerce a plain string to its enum member; None stays None."""
    if value is None or isinstance(value, kind):
        return value
    try:
        return kind(value)
    except ValueError:
        raise ValueError(f"{what}: {value!r} is not a valid {kind.__name__}") from None


def _check_int(value: Any, low: int, high: int, what: str) -> None:
    # type() rather than isinstance(): bool is an int subclass and must not pass
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{what} = {value!r} is not an int in {low}-{high}")


def _init_coordinates(obj: Any, what: str = "") -> None:
    """Check `obj.x` / `obj.y` are on the pitch and store them as floats."""
    x, y = obj.x, obj.y
    if type(x) is float and type(y) is float and 0 <= x <= PITCH_LENGTH and 0 <= y <= PITCH_WIDTH:
        return  # floats on the pitch already, as in every tracking frame: nothing to store
    where = f"{what}: " if what else ""
    for axis, limit in (("x", PITCH_LENGTH), ("y", PITCH_WIDTH)):
        value = getattr(obj, axis)
        # the range check alone rejects nan, inf and ints too large for a float
        if type(value) not in (int, float) or not 0 <= value <= limit:
            raise ValueError(f"{where}{axis} = {value!r} is not a finite number in 0-{limit:g}")
        object.__setattr__(obj, axis, float(value))


def _check_match_id(match_id: Any) -> None:
    if not (isinstance(match_id, str) and _ID.fullmatch(match_id)):
        raise ValueError(f"{match_id!r} is not a match id like m7 (lower-case letters and digits)")


def _check_club_id(team: Any, what: str) -> None:
    if not (isinstance(team, str) and _ID.fullmatch(team)):
        raise ValueError(f"{what}: {team!r} is not a club id")


def _check_period_clock(period: Any, clock_ms: Any, what: str) -> None:
    if type(period) is not int or period not in PERIODS:
        raise ValueError(f"{what}: period = {period!r} is not one of {PERIODS}")
    _check_int(clock_ms, 0, MAX_PERIOD_MS, f"{what}: clock_ms")


def _frame_number(period: Any, clock_ms: Any, what: str) -> int:
    _check_period_clock(period, clock_ms, what)
    if clock_ms % FRAME_MS:
        raise ValueError(f"{what}: clock_ms {clock_ms} is not a multiple of {FRAME_MS}")
    return (period - 1) * FRAMES_PER_PERIOD + clock_ms // FRAME_MS


def _check_actor(team: Any, player: Any, what: str) -> None:
    _check_club_id(team, what)
    if not (isinstance(player, str) and _PLAYER_ID.fullmatch(player) and team_of(player) == team):
        raise ValueError(f"{what}: player {player!r} is not in team {team}")


def _require_unique(what: str, values: Any) -> None:
    duplicates = sorted(str(v) for v, n in Counter(values).items() if n > 1)
    if duplicates:
        raise ValueError(f"{what}: {', '.join(duplicates)}")


def _check_keys(data: Any, cls: type, id_field: str) -> str:
    """Exactly the dataclass fields must be present; return the object's id for messages."""
    if not isinstance(data, dict):
        raise ValueError(f"{cls.__name__} must be a JSON object, got {type(data).__name__}")
    what = f"{cls.__name__} {data.get(id_field)!r}"
    expected = {f.name for f in fields(cls)}
    if missing := sorted(expected - data.keys()):
        raise ValueError(f"{what}: missing keys: {', '.join(missing)}")
    if unknown := sorted(str(k) for k in data.keys() - expected):
        raise ValueError(f"{what}: unknown keys: {', '.join(unknown)}")
    return what


def _point(value: Any, what: str) -> Point | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"x", "y"}:
        raise ValueError(f"{what}: expected a point with x and y, got {value!r}")
    try:
        return Point(value["x"], value["y"])
    except ValueError as e:
        raise ValueError(f"{what}: {e}") from None


def _player_position(value: Any, what: str) -> PlayerPosition:
    if not isinstance(value, dict) or set(value) != {"player", "x", "y"}:
        raise ValueError(f"{what}: expected a player position with player, x and y, got {value!r}")
    return PlayerPosition(value["player"], value["x"], value["y"])

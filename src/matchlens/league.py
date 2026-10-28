"""Fictional league: clubs and squads, loaded from the packaged data file.

`position` is the group generator v1 draws its 4-3-3 from; v2 reads the rest of a player (role,
side and physical limits) and of a club (formation and tactics).
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from matchlens.formations import FORMATIONS, ROLE_GROUP, ROLES, SIDES

POSITIONS = frozenset({"GK", "DF", "MF", "FW"})
SQUAD_SIZE = 18
MIN_GOALKEEPERS = 2
MIN_CLUBS = 2
_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")
_SHORT_NAME = re.compile(r"[A-Z]{3}")
# a player's limits, both ends included: top speed m/s (a keeper's, an outfield player's) and
# acceleration m/s²; stamina, work rate and the tactics are shares from 0 to 1
TOP_SPEED = {"GK": (6.5, 8.0), "outfield": (7.5, 9.8)}
ACCELERATION = (4.0, 6.5)
SHARE = (0.0, 1.0)
BUILD_UPS = frozenset({"short", "direct"})


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    number: int
    position: str
    role: str
    side: str
    top_speed: float
    acceleration: float
    stamina: float
    work_rate: float


@dataclass(frozen=True)
class Tactics:
    line_height: float  # 0 a deep block, 1 a high line
    press: float  # 0 hardly presses, 1 presses at once with two
    width: float  # 0 narrow, 1 wide
    build_up: str  # short or direct


@dataclass(frozen=True)
class Club:
    id: str
    name: str
    short_name: str
    city: str
    primary_colour: str
    secondary_colour: str
    formation: str
    tactics: Tactics
    players: tuple[Player, ...]


@dataclass(frozen=True)
class League:
    id: str
    name: str
    clubs: tuple[Club, ...]


def load_league() -> League:
    """The league shipped with the package (`matchlens/data/league.json`)."""
    text = files("matchlens").joinpath("data/league.json").read_text(encoding="utf-8")
    return parse_league(json.loads(text))


def parse_league(data: dict[str, Any]) -> League:
    """Build a League from its JSON form; raise ValueError if a squad rule is broken.

    Players are sorted by id, so the order of the file never changes what a seed generates.
    """
    clubs = tuple(_parse_club(c) for c in data["clubs"])
    if len(clubs) < MIN_CLUBS:
        raise ValueError(f"league has {len(clubs)} clubs, need {MIN_CLUBS}")
    _require_unique("club id", [c.id for c in clubs])
    _require_unique("club short name", [c.short_name for c in clubs])
    _require_unique("player id", [p.id for c in clubs for p in c.players])
    return League(id=data["id"], name=data["name"], clubs=clubs)


def _parse_club(data: dict[str, Any]) -> Club:
    players = tuple(sorted((Player(**p) for p in data["players"]), key=lambda p: p.id))
    club = Club(
        id=data["id"],
        name=data["name"],
        short_name=data["short_name"],
        city=data["city"],
        primary_colour=data["colours"]["primary"],
        secondary_colour=data["colours"]["secondary"],
        formation=data["formation"],
        tactics=Tactics(**data["tactics"]),
        players=players,
    )
    if not _SHORT_NAME.fullmatch(club.short_name):
        raise ValueError(f"{club.id}: short name {club.short_name!r} is not three capitals")
    if len(players) != SQUAD_SIZE:
        raise ValueError(f"{club.id}: squad has {len(players)} players, expected {SQUAD_SIZE}")
    for p in players:
        if not p.id.startswith(f"{club.id}-"):
            raise ValueError(f"{p.id}: player id does not start with its club id {club.id!r}")
        if p.position not in POSITIONS:
            raise ValueError(f"{p.id}: unknown position {p.position!r}")
        # type() rather than isinstance(): bool is an int subclass and must not pass
        if type(p.number) is not int or not 1 <= p.number <= 99:
            raise ValueError(f"{p.id}: shirt number {p.number!r} is not an int in 1-99")
        _check_player_v2(p)
    # after the type check: True == 1 and 7.0 == 7 would otherwise report as duplicates
    _require_unique(f"{club.id} shirt number", [p.number for p in players])
    goalkeepers = sum(p.position == "GK" for p in players)
    if goalkeepers < MIN_GOALKEEPERS:
        raise ValueError(f"{club.id}: {goalkeepers} goalkeepers, need {MIN_GOALKEEPERS}")
    for colour in (club.primary_colour, club.secondary_colour):
        if not _COLOUR.fullmatch(colour):
            raise ValueError(f"{club.id}: colour {colour!r} is not #RRGGBB")
    _check_club_v2(club)
    return club


def _check_player_v2(p: Player) -> None:
    if p.role not in ROLES:
        raise ValueError(f"{p.id}: unknown role {p.role!r}")
    if p.side not in SIDES:
        raise ValueError(f"{p.id}: unknown side {p.side!r}")
    if (p.role == "GK") != (p.position == "GK"):
        raise ValueError(f"{p.id}: role {p.role} does not fit position {p.position}")
    limits = (
        ("top speed", p.top_speed, TOP_SPEED["GK" if p.role == "GK" else "outfield"]),
        ("acceleration", p.acceleration, ACCELERATION),
        ("stamina", p.stamina, SHARE),
        ("work rate", p.work_rate, SHARE),
    )
    for what, value, (low, high) in limits:
        _require_within(f"{p.id}: {what}", value, low, high)


def _check_club_v2(club: Club) -> None:
    """A known formation and tactics, and a squad that fills the formation with a substitute for
    each group of roles (the keeper's is MIN_GOALKEEPERS)."""
    slots = FORMATIONS.get(club.formation)
    if slots is None:
        raise ValueError(f"{club.id}: unknown formation {club.formation!r}")
    tactics = club.tactics
    for what in ("line_height", "press", "width"):
        _require_within(f"{club.id}: tactics {what}", getattr(tactics, what), *SHARE)
    if tactics.build_up not in BUILD_UPS:
        raise ValueError(f"{club.id}: unknown build-up {tactics.build_up!r}")
    roles = Counter(p.role for p in club.players)
    needed = Counter(s.role for s in slots)
    for role in ROLES:
        if roles[role] < needed[role]:
            raise ValueError(
                f"{club.id}: {roles[role]} {role}, the {club.formation} needs {needed[role]}"
            )
    groups = Counter(ROLE_GROUP[p.role] for p in club.players if p.role != "GK")
    in_formation = Counter(ROLE_GROUP[s.role] for s in slots)
    for group, used in sorted(in_formation.items()):
        if groups[group] <= used:
            raise ValueError(
                f"{club.id}: no substitute in the {group}, {groups[group]} players for the "
                f"{club.formation}'s {used}"
            )


def _require_within(what: str, value: Any, low: float, high: float) -> None:
    # type() rather than isinstance(): a bool is an int and must not pass
    if type(value) not in (int, float):
        raise ValueError(f"{what} {value!r} is not a number in {low}-{high}")
    if not low <= value <= high:
        raise ValueError(f"{what} {value!r} is outside {low}-{high}")


def _require_unique(what: str, values: list[Any]) -> None:
    duplicates = sorted(str(v) for v, n in Counter(values).items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate {what}: {', '.join(duplicates)}")

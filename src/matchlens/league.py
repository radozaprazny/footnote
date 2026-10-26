"""Fictional league: clubs and squads, loaded from the packaged data file."""

import json
import re
from collections import Counter
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

POSITIONS = frozenset({"GK", "DF", "MF", "FW"})
SQUAD_SIZE = 18
MIN_GOALKEEPERS = 2
MIN_CLUBS = 2
_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")
_SHORT_NAME = re.compile(r"[A-Z]{3}")


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    number: int
    position: str


@dataclass(frozen=True)
class Club:
    id: str
    name: str
    short_name: str
    city: str
    primary_colour: str
    secondary_colour: str
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
    # after the type check: True == 1 and 7.0 == 7 would otherwise report as duplicates
    _require_unique(f"{club.id} shirt number", [p.number for p in players])
    goalkeepers = sum(p.position == "GK" for p in players)
    if goalkeepers < MIN_GOALKEEPERS:
        raise ValueError(f"{club.id}: {goalkeepers} goalkeepers, need {MIN_GOALKEEPERS}")
    for colour in (club.primary_colour, club.secondary_colour):
        if not _COLOUR.fullmatch(colour):
            raise ValueError(f"{club.id}: colour {colour!r} is not #RRGGBB")
    return club


def _require_unique(what: str, values: list[Any]) -> None:
    duplicates = sorted(str(v) for v, n in Counter(values).items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate {what}: {', '.join(duplicates)}")

"""Formations of generator v2: the ten outfield slots of each, in and out of possession.

A slot's position is in the team's own frame: `dx` metres ahead of its back line (the deepest
outfield slot sits at 0) and `y` across the pitch, 0 to 68, where L is y below 34 (the left as the
team attacks, the top of the screen when it attacks to the right). The movement layer places the
back line by the club's line height, spreads y by its width and shifts the block towards the ball,
then `to_pitch` turns the frame onto the pitch; the keeper is not a slot, he follows his own rule.
Unlike `stats.passing.team_frame`, which flips x alone, `to_pitch` turns a team that attacks to the
left half round, x and y, so its left stays its left. Widths are the normal ones: in possession
about 44 m and 34 m long, out of it about 34 m and 30 m, in the measured bands (PROGRESS, M9 item
1).
"""

from dataclasses import dataclass

from matchlens.events import PITCH_LENGTH, PITCH_WIDTH

ROLES = ("GK", "CB", "FB", "DM", "CM", "AM", "W", "ST")
SIDES = ("L", "C", "R")
# the groups a substitute must exist for: a squad has more players of each than its formation uses
ROLE_GROUP = {
    "GK": "goal",
    "CB": "back",
    "FB": "back",
    "DM": "midfield",
    "CM": "midfield",
    "AM": "midfield",
    "W": "attack",
    "ST": "attack",
}


@dataclass(frozen=True)
class Slot:
    role: str
    side: str
    attack: tuple[float, float]  # (dx, y) in possession
    defend: tuple[float, float]  # (dx, y) out of possession


def _slots(*rows: tuple[str, str, float, float, float, float]) -> tuple[Slot, ...]:
    return tuple(Slot(role, side, (ax, ay), (dx, dy)) for role, side, ax, ay, dx, dy in rows)


# role, side, in possession (dx, y), out of possession (dx, y)
FORMATIONS: dict[str, tuple[Slot, ...]] = {
    "4-3-3": _slots(
        ("CB", "L", 0, 26, 0, 27.5),
        ("CB", "R", 0, 42, 0, 40.5),
        ("FB", "L", 13, 13, 1.5, 17.5),
        ("FB", "R", 13, 55, 1.5, 50.5),
        ("DM", "C", 9, 34, 9, 34),
        ("CM", "L", 21, 24, 16, 25),
        ("CM", "R", 21, 44, 16, 43),
        ("W", "L", 30, 12, 23, 17),
        ("W", "R", 30, 56, 23, 51),
        ("ST", "C", 34, 34, 30, 34),
    ),
    "4-2-3-1": _slots(
        ("CB", "L", 0, 26, 0, 27.5),
        ("CB", "R", 0, 42, 0, 40.5),
        ("FB", "L", 13, 13, 1.5, 17.5),
        ("FB", "R", 13, 55, 1.5, 50.5),
        ("DM", "L", 10, 28, 9, 29),
        ("DM", "R", 10, 40, 9, 39),
        ("AM", "C", 24, 34, 19, 34),
        ("W", "L", 29, 12, 19, 18),
        ("W", "R", 29, 56, 19, 50),
        ("ST", "C", 34, 34, 30, 34),
    ),
    "4-4-2": _slots(
        ("CB", "L", 0, 26, 0, 27.5),
        ("CB", "R", 0, 42, 0, 40.5),
        ("FB", "L", 12, 13, 1, 17.5),
        ("FB", "R", 12, 55, 1, 50.5),
        ("CM", "L", 16, 28, 12, 29),
        ("CM", "R", 16, 40, 12, 39),
        ("W", "L", 26, 12, 13, 17),
        ("W", "R", 26, 56, 13, 51),
        ("ST", "L", 34, 30, 29, 30),
        ("ST", "R", 34, 38, 29, 38),
    ),
    "3-5-2": _slots(
        ("CB", "L", 0, 22, 0, 25),
        ("CB", "C", 0, 34, 0, 34),
        ("CB", "R", 0, 46, 0, 43),
        ("FB", "L", 24, 12, 3, 15),
        ("FB", "R", 24, 56, 3, 53),
        ("DM", "C", 9, 34, 8, 34),
        ("CM", "L", 19, 25, 15, 26),
        ("CM", "R", 19, 43, 15, 42),
        ("ST", "L", 34, 30, 29, 30),
        ("ST", "R", 34, 38, 29, 38),
    ),
}


def to_pitch(x: float, y: float, attacks_right: bool) -> tuple[float, float]:
    """A point of the team's frame, `x` metres from its own goal line, on the pitch: as it is for
    a team attacking to the right (towards x = 105), turned half round for one attacking left."""
    return (x, y) if attacks_right else (PITCH_LENGTH - x, PITCH_WIDTH - y)

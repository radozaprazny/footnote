"""Lineups of the packaged league for the movement layer's tests: per slot of a club's formation
the first free player of its role and side, else of its role (as M9 item 5 will pick them)."""

from matchlens.formations import FORMATIONS
from matchlens.league import load_league
from matchlens.targets import Team

CLUBS = {c.id: c for c in load_league().clubs}
PLAYERS = {p.id: p for c in CLUBS.values() for p in c.players}


def lineup(club):
    free = list(club.players)
    slots = {}
    for slot in FORMATIONS[club.formation]:
        pick = next((p for p in free if p.role == slot.role and p.side == slot.side), None)
        pick = pick or next(p for p in free if p.role == slot.role)
        free.remove(pick)
        slots[pick.id] = slot
    return slots, next(p.id for p in free if p.role == "GK")


def two_teams(home="cor", away="qrd", home_right=True):
    out = []
    for club, right in ((CLUBS[home], home_right), (CLUBS[away], not home_right)):
        slots, keeper = lineup(club)
        out.append(Team(club, slots, keeper, right))
    return tuple(out)

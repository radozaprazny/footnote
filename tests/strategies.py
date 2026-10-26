"""Hypothesis strategies for valid schema objects. The generator tests reuse them.

Each draw is valid on its own. A list of draws is not a valid stream: ids, order and possession
are not coherent across draws. `event_streams` draws whole streams with ids and time in order.
"""

import dataclasses
import math

from hypothesis import strategies as st

from matchlens.events import (
    FRAME_MS,
    MAX_BALL_SPEED,
    MAX_PERIOD_MS,
    MAX_SEED,
    MAX_SEQ,
    MAX_TRAVEL_MS,
    PERIODS,
    PITCH_LENGTH,
    PITCH_WIDTH,
    PLAYERS_PER_TEAM,
    SPECS,
    Event,
    EventType,
    MatchMeta,
    Outcome,
    PlayerPosition,
    Point,
    TrackingFrame,
    make_event_id,
    make_frame_id,
)
from matchlens.league import SQUAD_SIZE, load_league

CLUBS = tuple(club.id for club in load_league().clubs)  # the fictional Meridian League

match_ids = st.from_regex(r"[a-z0-9]{1,8}", fullmatch=True)
club_ids = st.sampled_from(CLUBS)
two_clubs = st.lists(club_ids, min_size=2, max_size=2, unique=True)
xs = st.floats(0, PITCH_LENGTH, allow_nan=False)
ys = st.floats(0, PITCH_WIDTH, allow_nan=False)
points = st.builds(Point, xs, ys)
periods = st.sampled_from(PERIODS)
clocks = st.integers(0, MAX_PERIOD_MS)
frame_clocks = st.integers(0, MAX_PERIOD_MS // FRAME_MS).map(lambda n: n * FRAME_MS)
seeds = st.integers(0, MAX_SEED)


def lineup(club: str) -> tuple[str, ...]:
    return tuple(f"{club}-p{i:02d}" for i in range(1, PLAYERS_PER_TEAM + 1))


@st.composite
def events(draw, match_id: str | None = None, team: str | None = None) -> Event:
    """A valid event of any type, with exactly the fields its type requires."""
    match_id = draw(match_ids) if match_id is None else match_id
    team = draw(club_ids) if team is None else team
    type_ = draw(st.sampled_from(list(EventType)))
    spec = SPECS[type_]
    seq = draw(st.integers(1 if spec.related else 0, MAX_SEQ))
    kwargs = {
        "event_id": make_event_id(match_id, seq),
        "period": draw(periods),
        "clock_ms": draw(clocks),
        "type": type_,
    }
    if spec.actor:
        number = draw(st.integers(1, SQUAD_SIZE))
        kwargs["team"] = team
        kwargs["player"] = f"{team}-p{number:02d}"
        kwargs["start"] = draw(points)
    if spec.outcomes:
        kwargs["outcome"] = draw(st.sampled_from(sorted(spec.outcomes)))
    if spec.travels:
        kwargs["clock_ms"] = draw(st.integers(0, MAX_PERIOD_MS - MAX_TRAVEL_MS))
        kwargs["end"] = draw(points)
        start, end = kwargs["start"], kwargs["end"]
        # slow enough for the ball-speed cap, with a margin for float rounding
        slowest = math.ceil(math.dist((start.x, start.y), (end.x, end.y)) / MAX_BALL_SPEED * 1000)
        kwargs["duration_ms"] = draw(st.integers(max(1, slowest + 1), MAX_TRAVEL_MS))
    if spec.restarts:
        kwargs["restart"] = draw(st.none() | st.sampled_from(sorted(spec.restarts)))
    if spec.recipient and kwargs["outcome"] is Outcome.COMPLETE:
        other = draw(st.integers(1, SQUAD_SIZE).filter(lambda n: n != number))
        kwargs["recipient"] = f"{team}-p{other:02d}"
    if spec.related:
        kwargs["related"] = make_event_id(match_id, draw(st.integers(0, seq - 1)))
    return Event(**kwargs)


@st.composite
def event_streams(draw) -> tuple[tuple[str, str], list[Event]]:
    """Two clubs and a stream of their events: ids and time in order, each period closed by
    period_end, anything else random. Not playable football (validate_match rejects it): ball
    flights overlap later events, events share a clock, either team acts at any time."""
    match_id = draw(match_ids)
    teams = draw(two_clubs)
    stream: list[Event] = []
    for period in PERIODS:
        clock = 0
        for _ in range(draw(st.integers(0, 20))):
            clock += draw(st.integers(0, 20_000))
            e = draw(
                events(match_id, draw(st.sampled_from(teams))).filter(
                    lambda e: (
                        e.type is not EventType.PERIOD_END and (not SPECS[e.type].related or stream)
                    )
                )
            )
            related = e.related and make_event_id(match_id, draw(st.integers(0, len(stream) - 1)))
            seq = len(stream)
            stream.append(
                dataclasses.replace(
                    e,
                    event_id=make_event_id(match_id, seq),
                    period=period,
                    clock_ms=clock,
                    related=related,
                )
            )
        clock += draw(st.integers(0, 5_000))
        stream.append(
            Event(make_event_id(match_id, len(stream)), period, clock, EventType.PERIOD_END)
        )
    return teams, stream


@st.composite
def frames(draw, match_id: str | None = None) -> TrackingFrame:
    match_id = draw(match_ids) if match_id is None else match_id
    home, away = draw(two_clubs)
    period, clock_ms = draw(periods), draw(frame_clocks)
    players = [PlayerPosition(p, draw(xs), draw(ys)) for p in lineup(home) + lineup(away)]
    return TrackingFrame(
        frame_id=make_frame_id(match_id, period, clock_ms),
        period=period,
        clock_ms=clock_ms,
        players=tuple(draw(st.permutations(players))),
        ball=draw(points),
    )


@st.composite
def match_metas(draw) -> MatchMeta:
    home, away = draw(two_clubs)
    return MatchMeta(draw(match_ids), home, away, lineup(home), lineup(away), draw(seeds))

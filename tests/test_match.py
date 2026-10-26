"""validate_match: each stream-level invariant has a broken case with a named message."""

import dataclasses
import re

import pytest
from strategies import CLUBS

from matchlens.events import EventType, Outcome, Point, Restart, make_event_id
from matchlens.generator import generate_match
from matchlens.match import Match, Snapshot, validate_match

NEEDED = {
    "type": [EventType.GOAL, EventType.SAVE, EventType.TACKLE],
    "restart": [Restart.THROW_IN, Restart.CORNER, Restart.PENALTY, Restart.GOAL_KICK],
}


@pytest.fixture(scope="module")
def match():
    """The first seed whose match has every event the broken cases need."""
    for seed in range(100):
        m = generate_match(seed)
        present = {e.type for e in m.events} | {e.restart for e in m.events}
        if all(v in present for values in NEEDED.values() for v in values):
            return m
    raise AssertionError("no seed below 100 has every needed event")


def renumbered(m, events):
    """Fresh contiguous ids; `related` follows the event it pointed at (first occurrence)."""
    mid = m.meta.match_id
    new_index = {}
    for i, e in enumerate(events):
        new_index.setdefault(e.event_id, i)
    return tuple(
        dataclasses.replace(
            e,
            event_id=make_event_id(mid, i),
            related=None if e.related is None else make_event_id(mid, new_index[e.related]),
        )
        for i, e in enumerate(events)
    )


def quick_pair(m):
    """Index of a snapshot that follows its predecessor within a second, same period."""
    return next(
        i
        for i in range(1, len(m.snapshots))
        if m.snapshots[i].period == m.snapshots[i - 1].period
        and m.snapshots[i].clock_ms - m.snapshots[i - 1].clock_ms <= 1000
    )


def first(match, **where):
    return next(
        i for i, e in enumerate(match.events) if all(getattr(e, k) == v for k, v in where.items())
    )


def with_event(match, i, **changes):
    events = list(match.events)
    events[i] = dataclasses.replace(events[i], **changes)
    return dataclasses.replace(match, events=tuple(events))


def with_snapshot(match, i, **changes):
    snaps = list(match.snapshots)
    snaps[i] = dataclasses.replace(snaps[i], **changes)
    return dataclasses.replace(match, snapshots=tuple(snaps))


def _no_events(m):
    return dataclasses.replace(m, events=())


def _bad_id(m):
    return with_event(m, 3, event_id=f"{m.meta.match_id}-e00099")


def _time_backwards(m):
    i = first(m, type=EventType.TACKLE)
    return with_event(m, i, clock_ms=m.events[i - 1].clock_ms - 1)


def _event_after_period_end(m):
    end = first(m, type=EventType.PERIOD_END)
    tackle = m.events[first(m, type=EventType.TACKLE)]
    events = list(m.events)
    events.insert(end + 1, dataclasses.replace(tackle, period=1, clock_ms=events[end].clock_ms))
    return dataclasses.replace(m, events=renumbered(m, events))


def _last_event_not_period_end(m):
    return dataclasses.replace(m, events=m.events[:-1])


def _team_not_playing(m):
    i = first(m, type=EventType.TACKLE)
    idle = next(c for c in CLUBS if c not in (m.meta.home, m.meta.away))
    return with_event(m, i, team=idle, player=f"{idle}-p01")


def _player_not_in_lineup(m):
    i = first(m, type=EventType.TACKLE)
    team = m.events[i].team
    lineup = m.meta.home_lineup if team == m.meta.home else m.meta.away_lineup
    bench = next(f"{team}-p{n:02d}" for n in range(1, 19) if f"{team}-p{n:02d}" not in lineup)
    return with_event(m, i, player=bench)


def _goal_without_goal_event(m):
    i = first(m, type=EventType.GOAL)
    return dataclasses.replace(m, events=renumbered(m, m.events[:i] + m.events[i + 1 :]))


def _goal_not_right_after_its_shot(m):
    """The shot is made harmless (off target) and the goal points at a pressure before it."""
    i = first(m, type=EventType.GOAL)
    events = list(m.events)
    events[i - 1] = dataclasses.replace(events[i - 1], outcome=Outcome.OFF_TARGET)
    filler = dataclasses.replace(
        events[i - 1],
        event_id=f"{m.meta.match_id}-e99999",
        type=EventType.PRESSURE,
        end=None,
        duration_ms=None,
        outcome=Outcome.RESISTED,
        restart=None,
    )
    events.insert(i, filler)
    events = list(renumbered(m, events))
    events[i + 1] = dataclasses.replace(events[i + 1], related=events[i].event_id)
    return dataclasses.replace(m, events=tuple(events))


def _tracking_starts_late(m):
    return dataclasses.replace(m, snapshots=m.snapshots[1:])


def _save_by_the_shooting_team(m):
    i = first(m, type=EventType.SAVE)
    shot = m.events[i - 1]
    return with_event(m, i, team=shot.team, player=shot.player)


def _goal_outside_the_posts(m):
    i = first(m, type=EventType.SHOT, outcome=Outcome.GOAL)
    end = m.events[i].end
    return with_event(m, i, end=Point(end.x, 34.0 + 5.0))


def _throw_in_from_the_middle(m):
    i = first(m, restart=Restart.THROW_IN)
    return with_event(m, i, start=Point(m.events[i].start.x, 20.0))


def _kick_off_off_centre(m):
    i = first(m, restart=Restart.KICK_OFF)
    return with_event(m, i, start=Point(50.0, 34.0))


def _corner_from_inside_the_pitch(m):
    i = first(m, restart=Restart.CORNER)
    s = m.events[i].start
    return with_event(m, i, start=Point(s.x, 20.0))


def _penalty_off_the_spot(m):
    i = first(m, restart=Restart.PENALTY)
    s = m.events[i].start
    return with_event(m, i, start=Point(s.x, s.y + 1.0))


def _goal_kick_from_outside_the_goal_area(m):
    i = first(m, restart=Restart.GOAL_KICK)
    s = m.events[i].start
    return with_event(m, i, start=Point(s.x, 60.0))


def _goal_by_another_player(m):
    i = first(m, type=EventType.GOAL)
    e = m.events[i]
    lineup = m.meta.home_lineup if e.team == m.meta.home else m.meta.away_lineup
    return with_event(m, i, player=next(p for p in lineup if p != e.player))


def _goal_counted_twice(m):
    i = first(m, type=EventType.GOAL)
    events = list(m.events)
    events.insert(i + 1, dataclasses.replace(events[i], event_id=f"{m.meta.match_id}-e99999"))
    return dataclasses.replace(m, events=renumbered(m, events))


def _recipient_not_where_the_ball_arrives(m):
    i = first(m, type=EventType.PASS, outcome=Outcome.COMPLETE)
    e = m.events[i]
    lineup = m.meta.home_lineup if e.team == m.meta.home else m.meta.away_lineup
    other = next(p for p in lineup if p not in (e.player, e.recipient))
    return with_event(m, i, recipient=other)


def _missing_snapshot(m):
    e = m.events[first(m, type=EventType.TACKLE)]
    snaps = [s for s in m.snapshots if (s.period, s.clock_ms) != (e.period, e.clock_ms)]
    return dataclasses.replace(m, snapshots=tuple(snaps))


def _tracking_ends_before_period_end(m):
    return dataclasses.replace(m, snapshots=m.snapshots[:-1])


def _ball_tuple_too_short(m):
    return with_snapshot(m, 6, ball=(1.0,))


def _player_tuple_too_short(m):
    players = list(m.snapshots[6].players)
    players[2] = players[2][:2]
    return with_snapshot(m, 6, players=tuple(players))


def _player_tuple_too_long(m):
    players = list(m.snapshots[6].players)
    players[2] = (*players[2], 0.0)
    return with_snapshot(m, 6, players=tuple(players))


def _player_id_not_a_string(m):
    players = list(m.snapshots[6].players)
    players[2] = (5, players[2][1], players[2][2])
    return with_snapshot(m, 6, players=tuple(players))


def _snapshot_clock_not_an_int(m):
    return with_snapshot(m, 6, clock_ms=None)


def _snapshot_period_three(m):
    return with_snapshot(m, 6, period=3)


def _save_without_save_event(m):
    i = first(m, type=EventType.SAVE)
    return dataclasses.replace(m, events=renumbered(m, m.events[:i] + m.events[i + 1 :]))


def _goal_after_a_blocked_shot(m):
    i = first(m, type=EventType.GOAL)
    return with_event(m, i - 1, outcome=Outcome.BLOCKED)


def far_corner(x, y):
    return (0.0 if x > 52.5 else 105.0, 0.0 if y > 34 else 68.0)


def _player_teleports(m):
    i = quick_pair(m)
    players = list(m.snapshots[i].players)
    players[3] = (players[3][0], *far_corner(players[3][1], players[3][2]))
    return with_snapshot(m, i, players=tuple(players))


def _ball_teleports(m):
    i = quick_pair(m)
    return with_snapshot(m, i, ball=far_corner(*m.snapshots[i].ball))


def _player_order_changes(m):
    s = m.snapshots[6]
    players = list(s.players)
    players[0], players[1] = players[1], players[0]
    return with_snapshot(m, 6, players=tuple(players))


def _twenty_one_players(m):
    return with_snapshot(m, 6, players=m.snapshots[6].players[:-1])


def _ball_off_the_pitch(m):
    return with_snapshot(m, 6, ball=(105.5, 34.0))


def _no_second_half_tracking(m):
    return dataclasses.replace(m, snapshots=tuple(s for s in m.snapshots if s.period == 1))


def _snapshot_time_repeats(m):
    return with_snapshot(m, 6, clock_ms=m.snapshots[5].clock_ms)


def _event_ball_mismatch(m):
    i = first(m, type=EventType.TACKLE)
    s = m.events[i].start
    return with_event(m, i, start=Point(s.x + 0.5, s.y))


def _actor_elsewhere(m):
    i = first(m, type=EventType.TACKLE)
    e = m.events[i]
    lineup = m.meta.home_lineup if e.team == m.meta.home else m.meta.away_lineup
    other = next(p for p in lineup if p != e.player)
    return with_event(m, i, player=other)


BROKEN = [
    (_no_events, "no events"),
    (_bad_id, "event number 3 should have id"),
    (_time_backwards, "time goes backwards"),
    (_event_after_period_end, "after the end of period 1"),
    (_last_event_not_period_end, "each period must end with period_end"),
    (_team_not_playing, "is not playing"),
    (_player_not_in_lineup, "is not in the"),
    (_goal_without_goal_event, "a goal shot must be followed by its goal"),
    (_goal_not_right_after_its_shot, "goal must directly follow its shot"),
    (_save_by_the_shooting_team, "save must follow a saved shot by the other team"),
    (_goal_outside_the_posts, "a goal must end on the goal line between the posts"),
    (_throw_in_from_the_middle, "a throw_in is not taken from"),
    (_kick_off_off_centre, "a kick_off is not taken from"),
    (_corner_from_inside_the_pitch, "a corner is not taken from"),
    (_penalty_off_the_spot, "a penalty is not taken from"),
    (_goal_kick_from_outside_the_goal_area, "a goal_kick is not taken from"),
    (_goal_by_another_player, "goal must follow a goal shot by the same player"),
    (_goal_counted_twice, "goal must directly follow its shot"),
    (_recipient_not_where_the_ball_arrives, "in tracking"),
    (_tracking_ends_before_period_end, "tracking of period 2 must end at period_end"),
    (_ball_tuple_too_short, "snapshot 1/"),
    (_player_tuple_too_short, "every player entry must be (id, x, y)"),
    (_player_tuple_too_long, "every player entry must be (id, x, y)"),
    (_player_id_not_a_string, "players are not the two lineups"),
    (_snapshot_clock_not_an_int, "clock_ms = None is not an int"),
    (_snapshot_period_three, "period = 3 is not one of"),
    (_save_without_save_event, "a saved shot must be followed by its save"),
    (_goal_after_a_blocked_shot, "goal must follow a goal shot by the same player"),
    (_missing_snapshot, "no snapshot at"),
    (_player_teleports, "moved faster than 9.5 m/s"),
    (_ball_teleports, "the ball moved faster than 50"),
    (_player_order_changes, "player order changed"),
    (_twenty_one_players, "players are not the two lineups"),
    (_ball_off_the_pitch, "x = 105.5 is not a finite number"),
    (_no_second_half_tracking, "tracking must cover both periods"),
    (_tracking_starts_late, "tracking of period 1 must start at 0"),
    (_snapshot_time_repeats, "not after the previous snapshot"),
    (_event_ball_mismatch, "the ball is not at"),
    (_actor_elsewhere, "in tracking"),
]


@pytest.mark.parametrize(("breaker", "message"), BROKEN, ids=lambda x: "")
def test_broken_match_is_refused(match, breaker, message):
    validate_match(match)  # the fixture itself is fine
    with pytest.raises(ValueError, match=re.escape(message)):
        validate_match(breaker(match))


def test_match_score_and_frames_on_a_tiny_hand_built_match():
    lineup = {t: tuple(f"{t}-p{i:02d}" for i in range(1, 12)) for t in ("cor", "vel")}
    from matchlens.events import Event, MatchMeta

    meta = MatchMeta("m1", "cor", "vel", lineup["cor"], lineup["vel"], 1)
    players = tuple((p, 10.0, 20.0) for p in lineup["cor"] + lineup["vel"])
    snaps = (
        Snapshot(1, 0, (52.5, 34.0), players),
        Snapshot(1, 250, (62.5, 34.0), players),  # off the 100 ms grid on purpose
        Snapshot(1, 300, (60.0, 34.0), players),
        Snapshot(2, 0, (52.5, 34.0), players),
        Snapshot(2, 100, (52.5, 34.0), players),
    )
    events = (
        Event("m1-e00000", 1, 0, EventType.PERIOD_END),
        Event("m1-e00001", 2, 0, EventType.PERIOD_END),
    )
    m = Match(meta, events, snaps)
    assert m.score() == (0, 0)
    frames = list(m.frames())
    assert [(f.period, f.clock_ms, f.ball.x) for f in frames] == [
        (1, 0, 52.5),
        (1, 100, 56.5),
        (1, 200, 60.5),
        (1, 300, 60.0),
        (2, 0, 52.5),
        (2, 100, 52.5),
    ]

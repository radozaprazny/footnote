"""The Moment Detector: finds the key moments of a match's events, with no LLM.

A key moment is a goal, a saved shot or a shot that hits the woodwork. Its
triggers are the shot and, for a goal or a save, the event that ends it; it runs from the shot to
the instant the ball arrives (the goal or the save, or the woodwork at the end of the shot's
flight). The Detector reads only the events up to `until`, a live match's prefix, and returns
the moments that have ended by then, so a prefix yields exactly the full match's moments that
end inside it, with the same ids.

A moment's facts are the engine's `facts_at` its end (clock, minute, score, possession, flow,
the teams' passing, shirt numbers): the ones the Guard looks up. They go into the case without
their id lists (`facts.brief`, as the MCP server sends them): the case is logged whole at every
handoff, a possession fact cites about 1 700 events, and the Guard takes a fact's evidence from
the engine, never from the case.
"""

from matchlens.events import EventType, Outcome, display_clock, parse_event_id
from matchlens.explain.state import MomentCase
from matchlens.facts import Time, brief, facts_at
from matchlens.match import Match


def detect(match: Match, run_id: str, until: Time | None = None) -> list[MomentCase]:
    """The key moments of `match` that have ended by `until` (period, clock_ms), or by its last
    event, in the order they end. A moment's id names its shot: `m7-k00072` for `m7-e00072`."""
    if until is None:
        until = max(((e.period, e.clock_ms) for e in match.events), default=(1, 0))
    period, clock_ms = until
    until = (period, clock_ms)  # a list from JSON would not compare with the events' tuples
    display_clock(*until)  # checks period and clock
    events = [e for e in match.events if (e.period, e.clock_ms) <= until]
    shots = {e.event_id: e for e in events if e.type is EventType.SHOT}
    cases = []
    for e in events:
        if e.type in (EventType.GOAL, EventType.SAVE):
            if e.related not in shots:
                raise ValueError(f"{e.event_id}: {e.related} is no shot of the match")
            shot, end, triggers = shots[e.related], e.clock_ms, (e.related, e.event_id)
        elif e.type is EventType.SHOT and e.outcome is Outcome.WOODWORK:
            shot, end, triggers = e, e.clock_ms + e.duration_ms, (e.event_id,)
        else:
            continue
        if (e.period, end) <= until:
            cases.append(
                MomentCase(
                    run_id=run_id,
                    match_id=match.meta.match_id,
                    moment_id=f"{match.meta.match_id}-k{parse_event_id(shot.event_id)[1]:05d}",
                    trigger_ids=triggers,
                    period=e.period,
                    start_ms=shot.clock_ms,
                    end_ms=end,
                    display_clock=display_clock(e.period, end),
                    facts=tuple(brief(f) for f in facts_at(match, e.period, end)),
                )
            )
    return sorted(cases, key=lambda c: (c.period, c.end_ms, c.moment_id))

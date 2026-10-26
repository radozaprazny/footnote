"""Replay a generated match as Server-Sent Events.

The replay runs on one continuous timeline: period 2 starts where period 1 ended, with no
half-time break, so a replay at speed 1 lasts the playing time. Every message carries
`emitted_at_ms`, the server's wall clock when the message left the generator, so a client can
measure event-to-overlay latency (M4). Each match event is sent with its event id as the SSE
`id`, so a reconnecting client resumes after the last event it saw (`Last-Event-ID`).

The live stream (`live`) merges the events with tracking frames at a chosen rate and the overlay
cues into one stream on the same timeline; every message has an id, so it resumes after any.
"""

import json
import time
from asyncio import sleep as asyncio_sleep
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property, partial
from itertools import islice

from matchlens.events import (
    FRAME_MS,
    Event,
    TrackingFrame,
    display_clock,
    make_frame_id,
    parse_event_id,
)
from matchlens.match import Match
from matchlens.render.cues import Cue

HEARTBEAT_S = 15.0  # longest silence on the wire; proxies close idle streams
RETRY_MS = 1000  # how long a browser waits before it reconnects after a network error
YIELD_EVERY = 100  # messages between event-loop turns at speed 0 (a full match takes ~12 ms)
LIVE_HZ = (1, 2, 5, 10)  # tracking rates of the live stream: divisors of the 10 Hz tracking
DEFAULT_HZ = 5


@dataclass
class Clock:
    """Time sources of a replay, injectable so tests run without waiting."""

    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio_sleep
    wall_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000


def replay_offsets(events: Sequence[Event]) -> list[int]:
    """Milliseconds from the first kick-off of each event; period 2 follows period 1 directly."""
    first_half = max((e.clock_ms for e in events if e.period == 1), default=0)
    return [e.clock_ms + (first_half if e.period == 2 else 0) for e in events]


def resume_index(events: Sequence[Event], last_event_id: str | None) -> int:
    """Index of the first event to send: 0, or the event after `last_event_id`.

    ValueError if the id is malformed or not an event of this match.
    """
    if not last_event_id:
        return 0
    _, seq = parse_event_id(last_event_id)
    if seq >= len(events) or events[seq].event_id != last_event_id:
        raise ValueError(f"{last_event_id} is not an event of this match")
    return seq + 1


def end_id(match_id: str) -> str:
    """SSE id of the `end` message. A browser that reconnects with it gets 204 and stops."""
    return f"{match_id}-end"


def sse(kind: str, data: dict, event_id: str | None = None, retry_ms: int | None = None) -> str:
    """One SSE message with a single data line: JSON escapes every newline and control char.

    ValueError if `kind` or `event_id` would break the framing, or `data` holds NaN/Infinity
    (browsers' JSON.parse rejects them).
    """
    for name, value in (("kind", kind), ("event_id", event_id)):
        if value is not None and any(c in value for c in "\r\n\0"):
            raise ValueError(f"{name} {value!r} contains a line break or NUL")
    lines = []
    if retry_ms is not None:
        lines.append(f"retry: {retry_ms}")
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {kind}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'), allow_nan=False)}")
    return "\n".join(lines) + "\n\n"


async def paced(
    timed: Iterable[tuple[int, Callable[[], str]]], speed: float, clock: Clock
) -> AsyncIterator[str]:
    """Render and send each (offset_ms, render) when its offset is due, the first one at once.

    Waits are measured against a monotonic clock from the first message, so they do not drift;
    a silence longer than HEARTBEAT_S is broken by an SSE comment. Speed 0 sends everything at
    once, giving the event loop a turn every YIELD_EVERY messages so one fast client does not
    stall the other streams. `render` runs when the message leaves, so its `emitted_at_ms` is
    the sending time.
    """
    started = clock.monotonic()
    first: int | None = None
    for n, (offset, render) in enumerate(timed):
        first = offset if first is None else first
        if speed > 0:
            due = (offset - first) / 1000 / speed
            while (wait := due - (clock.monotonic() - started)) > 0:
                await clock.sleep(min(wait, HEARTBEAT_S))
                if wait > HEARTBEAT_S:
                    yield f": heartbeat {clock.wall_ms()}\n\n"
        elif n and n % YIELD_EVERY == 0:
            await asyncio_sleep(0)  # a turn for the other streams, not a wait
        yield render()


def meta_message(match: Match, clock: Clock, **extra) -> str:
    data = {"meta": match.meta.to_dict(), **extra, "emitted_at_ms": clock.wall_ms()}
    return sse("meta", data, retry_ms=RETRY_MS)


def end_message(match: Match, clock: Clock) -> str:
    data = {"match_id": match.meta.match_id, "emitted_at_ms": clock.wall_ms()}
    return sse("end", data, event_id=end_id(match.meta.match_id))


def event_message(e: Event, offset: int, clock: Clock) -> str:
    payload = {
        "event": e.to_dict(),
        "display_clock": display_clock(e.period, e.clock_ms),
        "replay_ms": offset,
        "emitted_at_ms": clock.wall_ms(),
    }
    return sse("match_event", payload, event_id=e.event_id)


async def replay(
    match: Match, speed: float, start: int = 0, clock: Clock | None = None
) -> AsyncIterator[str]:
    """The SSE stream of `match` from event `start` on; speed 0 sends everything at once.

    Messages: `meta` (lineups), one `match_event` per event, then `end`, paced by `paced`. A
    resumed stream sends its first event at once: the rest of the gap before it is not waited
    out again.
    """
    clock = clock or Clock()
    events = match.events
    offsets = replay_offsets(events)
    yield meta_message(match, clock)
    timed = (
        (offset, partial(event_message, e, offset, clock))
        for e, offset in zip(events[start:], offsets[start:], strict=True)
    )
    async for chunk in paced(timed, speed, clock):
        yield chunk
    yield end_message(match, clock)


# --- live stream -----------------------------------------------------------------------------


class Kind:
    """Message kinds of the live stream; at the same moment frames go first, then events, then
    cues, so a cue never precedes an event of its moment."""

    FRAME = "frame"
    EVENT = "match_event"
    CUE = "cue"


RANK = {Kind.FRAME: 0, Kind.EVENT: 1, Kind.CUE: 2}


@dataclass(frozen=True, slots=True)
class Item:
    """One message of the live stream before it is rendered. Frames carry no object: they are
    interpolated when sent (a whole match at 10 Hz would hold 57 000 of them)."""

    period: int
    clock_ms: int
    kind: str
    id: str
    obj: Event | Cue | None = None


@dataclass(frozen=True)
class LiveTimeline:
    """Every message of one match's live stream at one tracking rate, in sending order."""

    match_id: str
    hz: int
    items: tuple[Item, ...]
    first_half_ms: int  # where period 2 starts on the replay timeline, so the last frame of
    # period 1 and the kick-off frame of period 2 share a `replay_ms`

    def offset(self, item: Item) -> int:
        return item.clock_ms + (self.first_half_ms if item.period == 2 else 0)

    def resume_index(self, last_id: str | None) -> int:
        """Index of the first item to send: 0, or the item after `last_id`.

        ValueError if `last_id` is no message id of this stream.
        """
        if not last_id:
            return 0
        index = self._index.get(last_id)
        if index is None:
            raise ValueError(f"{last_id} is not a message of this stream")
        return index + 1

    @cached_property
    def _index(self) -> dict[str, int]:
        return {item.id: n for n, item in enumerate(self.items)}


def live_timeline(
    match_id: str,
    events: Sequence[Event],
    cues: Sequence[Cue],
    tracking_ends: Mapping[int, int],
    hz: int = DEFAULT_HZ,
) -> LiveTimeline:
    """Frames every 1/`hz` s of each period up to its last tracking clock (`tracking_ends`),
    the events and the cues, ordered by match time; a cue is placed at its `due` moment, after
    the frames and events of that moment.

    ValueError if `hz` is not in LIVE_HZ, or a cue is due before an event it or one of its
    renditions or translations cites, or cites an event that is not in `events`.
    """
    if hz not in LIVE_HZ:
        raise ValueError(f"hz {hz} is not one of {LIVE_HZ}")
    when = {e.event_id: (e.period, e.clock_ms) for e in events}
    for c in cues:
        texts = (*c.renditions, *c.translations)
        for event_id in dict.fromkeys([*c.event_ids, *(i for r in texts for i in r.event_ids)]):
            if event_id not in when:
                raise ValueError(f"cue {c.cue_id} cites {event_id}, which is not in the stream")
            if when[event_id] > c.due:
                raise ValueError(f"cue {c.cue_id} is due before the event {event_id} it cites")
    step = FRAME_MS * (10 // hz)
    items = [
        Item(period, clock, Kind.FRAME, make_frame_id(match_id, period, clock))
        for period, end in sorted(tracking_ends.items())
        for clock in range(0, end + 1, step)
    ]
    items += [Item(e.period, e.clock_ms, Kind.EVENT, e.event_id, e) for e in events]
    items += [Item(*c.due, Kind.CUE, c.cue_id, c) for c in cues]
    items.sort(key=lambda i: (i.period, i.clock_ms, RANK[i.kind]))  # stable: input order kept
    first_half = max((e.clock_ms for e in events if e.period == 1), default=0)
    return LiveTimeline(match_id, hz, tuple(items), first_half)


def tracking_ends(match: Match) -> dict[int, int]:
    """The last tracking clock of each period."""
    ends: dict[int, int] = {}
    for s in match.snapshots:
        ends[s.period] = max(ends.get(s.period, 0), s.clock_ms)
    return ends


def frame_payload(f: TrackingFrame) -> dict:
    """A frame in compact form: positions in metres to the centimetre, as [x, y] and
    [player, x, y] lists."""
    return {
        "frame_id": f.frame_id,
        "period": f.period,
        "clock_ms": f.clock_ms,
        "display_clock": display_clock(f.period, f.clock_ms),
        "ball": [round(f.ball.x, 2), round(f.ball.y, 2)],
        "players": [[p.player, round(p.x, 2), round(p.y, 2)] for p in f.players],
    }


async def live(
    match: Match,
    timeline: LiveTimeline,
    speed: float,
    start: int = 0,
    clock: Clock | None = None,
) -> AsyncIterator[str]:
    """The live SSE stream of `match` from item `start` of `timeline` on: `meta` (lineups, `hz`
    and `first_half_ms`), then `frame`, `match_event` and `cue` messages in timeline order,
    each with its id, then `end`. Paced like `replay`; a resumed stream sends its first item
    at once.
    """
    clock = clock or Clock()
    # the items from `start` on, read in place: a copy of the rest per open stream costs memory
    rest = partial(islice, timeline.items, start, None)
    first_frame = next((i for i in rest() if i.kind == Kind.FRAME), None)
    every_ms = FRAME_MS * (10 // timeline.hz)
    frames = (
        match.frames(every_ms, (first_frame.period, first_frame.clock_ms))
        if first_frame
        else iter(())
    )

    def render(item: Item) -> str:
        if item.kind == Kind.FRAME:
            frame = next(frames)
            if frame.frame_id != item.id:
                raise RuntimeError(f"tracking out of step: {frame.frame_id} for {item.id}")
            data = frame_payload(frame)
        else:
            name = "event" if item.kind == Kind.EVENT else "cue"
            data = {
                name: item.obj.to_dict(),
                "display_clock": display_clock(item.period, item.clock_ms),
            }
        data |= {"replay_ms": timeline.offset(item), "emitted_at_ms": clock.wall_ms()}
        return sse(item.kind, data, event_id=item.id)

    yield meta_message(match, clock, hz=timeline.hz, first_half_ms=timeline.first_half_ms)
    timed = ((timeline.offset(item), partial(render, item)) for item in rest())
    async for chunk in paced(timed, speed, clock):
        yield chunk
    yield end_message(match, clock)

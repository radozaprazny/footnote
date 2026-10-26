"""MCP server: the facts of generated matches for agents, over stdio or streamable HTTP."""

import threading
from collections.abc import Iterable
from functools import cache
from typing import TypedDict

import anyio
from mcp.server.fastmcp import FastMCP

from matchlens import facts
from matchlens.match import Match

INSTRUCTIONS = (
    "Facts of synthetic football matches. Every number a narrative uses is a fact's `display`, "
    "written as is. Facts come with the number of their event and frame ids; `fact_evidence` "
    "gives the ids. Cite the fact id and its event ids (frame ids for a tracking value; a shirt "
    "number, the clock, the minute and a zero count or rate have none). `momentum` is a team's "
    "share of the weighted attacking actions (shots, passes or clearances into the final "
    "third, balls won high), not possession. `chaos` is an index from 0 (control) to 100 "
    "(chaos) on which a typical whole match scores 50; it is no percentage. A possession change "
    "is any change of the team on the ball, in play or at a restart."
)


class Evidence(TypedDict):
    fact_id: str
    event_ids: list[str]
    frame_ids: list[str]


def create_server(matches: Iterable[Match], host: str = "127.0.0.1", port: int = 8001) -> FastMCP:
    """A server for `matches`, looked up by match id; a match's facts are computed once.

    Tools return facts without their id lists (a possession fact cites about 1 700 events),
    with `event_count` and `frame_count` instead; `fact_evidence` returns the ids of one fact.
    """
    registry: dict[str, Match] = {}
    for m in matches:
        if m.meta.match_id in registry:
            raise ValueError(f"duplicate match id {m.meta.match_id}")
        registry[m.meta.match_id] = m

    def match(match_id: str) -> Match:
        if match_id not in registry:
            raise ValueError(f"unknown match {match_id}")
        return registry[match_id]

    @cache
    def computed(match_id: str) -> list[facts.Fact]:
        return facts.match_facts(match(match_id))

    lock = threading.Lock()

    async def whole(match_id: str) -> list[facts.Fact]:
        """The first call computes the match for seconds: in a thread, so the server keeps
        answering, and under a lock, so two first calls compute it once."""

        def once() -> list[facts.Fact]:
            with lock:
                return computed(match_id)

        match(match_id)  # an unknown id fails here, not in the thread
        return await anyio.to_thread.run_sync(once)

    def at(match_id: str, period: int, clock_ms: int) -> list[facts.Fact]:
        return facts.facts_at(match(match_id), period, clock_ms)

    server = FastMCP(
        "matchlens", instructions=INSTRUCTIONS, host=host, port=port, log_level="WARNING"
    )

    @server.tool()
    def list_matches() -> list[dict]:
        """The matches served: id, home club, away club."""
        return [
            {"match_id": m.meta.match_id, "home": m.meta.home, "away": m.meta.away}
            for m in registry.values()
        ]

    @server.tool()
    async def match_facts(match_id: str) -> list[dict]:
        """The final totals of a whole match (for a moment of a live match use `facts_at`):
        score, possession, passing, pressing, momentum, possession changes, average possession
        length, chaos, distance, top speed, hard shots, shirt numbers; and readings (names
        ending in `_reading`): the engine's judgement of a fact as a phrase to write as it is."""
        return [facts.brief(f) for f in await whole(match_id)]

    @server.tool()
    async def player_facts(match_id: str, player: str) -> list[dict]:
        """The final totals of one player (an id like `cor-p07`) over the whole match."""
        meta = match(match_id).meta
        if player not in meta.home_lineup + meta.away_lineup:
            raise ValueError(f"{match_id}: {player} is not in a lineup")
        return [facts.brief(f) for f in await whole(match_id) if f.player == player]

    @server.tool()
    def facts_at(match_id: str, period: int, clock_ms: int) -> list[dict]:
        """What is known at a moment of the live match (period 1 or 2, milliseconds since that
        period's kick-off): clock, minute, score, possession, the teams' passing, pressing,
        momentum, possession changes, average possession length, chaos, shirt numbers; and
        readings (names ending in `_reading`): the engine's judgement of a fact as a phrase to
        write as it is, e.g. "take the lead", "on top"."""
        return [facts.brief(f) for f in at(match_id, period, clock_ms)]

    @server.tool()
    async def fact_evidence(match_id: str, fact_id: str) -> Evidence:
        """The event and frame ids of one fact, from any of the other tools."""
        scope = fact_id.split("/")[2] if fact_id.count("/") == 3 else ""
        if scope.startswith(("at-", "to-", "last5-")):  # a moment's fact: (period, clock_ms)
            period, clock_ms = (int(n) for n in scope.split("-")[1:3])
            candidates = at(match_id, period, clock_ms)
        else:
            candidates = await whole(match_id)
        for f in candidates:
            if f.fact_id == fact_id:
                return Evidence(
                    fact_id=f.fact_id, event_ids=list(f.event_ids), frame_ids=list(f.frame_ids)
                )
        raise ValueError(f"unknown fact {fact_id}")

    return server

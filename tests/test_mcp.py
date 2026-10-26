import time

import anyio
import pytest
import real
from mcp.shared.memory import create_connected_server_and_client_session

from matchlens.facts import facts_at
from matchlens.mcp import create_server


def brief(f) -> dict:
    """What a tool returns for a fact: no id lists, their sizes."""
    d = {k: v for k, v in f.to_dict().items() if k not in ("event_ids", "frame_ids")}
    return d | {"event_count": len(f.event_ids), "frame_count": len(f.frame_ids)}


def test_an_mcp_client_lists_the_tools_and_reads_the_facts():
    m7, m3 = real.match(7), real.match(3)
    server = create_server([m7, m3])

    async def session():
        async with create_connected_server_and_client_session(server) as client:

            async def call(tool, **args):
                result = await client.call_tool(tool, args)
                assert not result.isError, (tool, args, result.content)
                content = result.structuredContent  # a list comes wrapped as "result"
                return content["result"] if set(content) == {"result"} else content

            tools = {t.name for t in (await client.list_tools()).tools}
            assert tools == {"list_matches", "match_facts", "player_facts", "facts_at",
                             "fact_evidence"}  # fmt: skip
            assert await call("list_matches") == [
                {"match_id": m.meta.match_id, "home": m.meta.home, "away": m.meta.away}
                for m in (m7, m3)
            ]
            for m in (m7, m3):  # each match by its own id
                got = await call("facts_at", match_id=m.meta.match_id, period=2, clock_ms=1_343_000)
                assert got == [brief(f) for f in facts_at(m, 2, 1_343_000)]
            for m in (m7, m3):  # the second match too, by its own id
                match_id, player = m.meta.match_id, m.meta.home_lineup[5]
                whole = await call("match_facts", match_id=match_id)
                assert whole == [brief(f) for f in real.facts(m.meta.seed)]
                own = await call("player_facts", match_id=match_id, player=player)
                assert own == [f for f in whole if f["player"] == player] != []
                moment = facts_at(m, 2, 1_343_000)
                picked = [
                    next(f for f in real.facts(m.meta.seed) if f.name == name)
                    for name in ("possession", "distance", "top_speed", "shirt_number")
                ] + [
                    next(f for f in moment if f.fact_id.split("/")[2].startswith(scope))
                    for scope in ("at-", "to-", "last5-")
                ]
                for f in picked:
                    ids = await call("fact_evidence", match_id=match_id, fact_id=f.fact_id)
                    assert ids == {
                        "fact_id": f.fact_id,
                        "event_ids": list(f.event_ids),
                        "frame_ids": list(f.frame_ids),
                    }
            for tool, args in [
                ("match_facts", {"match_id": "m9"}),
                ("player_facts", {"match_id": "m7", "player": "slt-p99"}),
                ("facts_at", {"match_id": "m7", "period": 3, "clock_ms": 0}),
                ("fact_evidence", {"match_id": "m7", "fact_id": "m7/nothing/match/all"}),
                ("fact_evidence", {"match_id": "m3", "fact_id": "m7/possession/match/slt"}),
            ]:
                result = await client.call_tool(tool, args)
                assert result.isError, (tool, args)

    anyio.run(session)


def test_a_match_is_served_once():
    m = real.match(7)
    with pytest.raises(ValueError, match="duplicate match id m7"):
        create_server([m, m])


def test_two_first_calls_compute_a_match_once(monkeypatch):
    calls = []

    def slow_facts(match):
        calls.append(match.meta.match_id)
        time.sleep(0.2)  # long enough for the four calls to overlap
        return real.facts(7)

    monkeypatch.setattr("matchlens.facts.match_facts", slow_facts)
    server = create_server([real.match(7)])

    async def session():
        async with (
            create_connected_server_and_client_session(server) as client,
            anyio.create_task_group() as tg,
        ):
            for _ in range(4):
                tg.start_soon(client.call_tool, "match_facts", {"match_id": "m7"})

    anyio.run(session)
    assert calls == ["m7"]

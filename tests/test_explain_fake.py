import asyncio
import json

import pytest
from agent_framework import Message

from matchlens.explain.analyst import moment_prompt
from matchlens.explain.detector import detect
from matchlens.explain.fake import FakeChatClient, ScriptExhausted, by_moment, echo
from matchlens.explain.guard import check, moment_evidence
from matchlens.explain.state import Draft
from matchlens.generator import generate_match


def ask(client, text="hello", **kwargs):
    return asyncio.run(client.get_response([Message(role="user", contents=[text])], **kwargs))


def test_replies_come_in_script_order_and_requests_are_kept():
    client = FakeChatClient(["one", "two"])
    assert [ask(client, "a").text, ask(client, "bb").text] == ["one", "two"]
    assert [msgs[-1].text for msgs, _ in client.requests] == ["a", "bb"]


def test_token_counts_are_characters_in_and_out():
    client = FakeChatClient(["four"])
    usage = ask(client, "hello").usage_details
    assert (usage["input_token_count"], usage["output_token_count"]) == (5, 4)


def test_a_scripted_exception_is_raised_and_an_empty_script_says_so():
    client = FakeChatClient([TimeoutError("Foundry")])
    with pytest.raises(TimeoutError, match="Foundry"):
        ask(client)
    with pytest.raises(ScriptExhausted, match="no scripted reply left for request 2"):
        ask(client)
    assert issubclass(ScriptExhausted, AssertionError)  # no Analyst catches it as a failed call


def test_streaming_is_not_faked():
    async def stream():
        async for _ in FakeChatClient(["x"]).get_response(
            [Message(role="user", contents=["hi"])], stream=True
        ):
            pass

    with pytest.raises(NotImplementedError):
        asyncio.run(stream())


def test_a_script_may_be_a_function_of_the_request_text():
    client = FakeChatClient(lambda prompt: prompt.upper())
    assert [ask(client, "ab").text, ask(client, "cd").text] == ["AB", "CD"]
    assert len(client.requests) == 2


def test_by_moment_answers_each_moment_s_attempts_in_turn():
    script = by_moment(
        {"m7-k00072": ["first", "second"], "m7-k00207": [lambda p: p.split("\n")[-1]]}
    )
    first = "Moment m7-k00072 at clock 04:18.\nFacts:"
    retry = first + '\nEarlier attempts, all rejected:\n- Attempt 1: "x"'
    other = "Moment m7-k00207 at clock 12:34.\nshort"
    client = FakeChatClient(script)
    assert [ask(client, t).text for t in (other, retry, first)] == ["short", "second", "first"]
    with pytest.raises(ScriptExhausted, match="no scripted reply 2 for moment m7-k00207"):
        ask(client, other + '\n- Attempt 1: "x"')
    with pytest.raises(ScriptExhausted, match="no scripted reply 1 for moment m7-k1"):
        ask(client, "Moment m7-k1 at clock 00:01.")
    with pytest.raises(ScriptExhausted, match="names no moment"):
        ask(client, "hello")


def test_echo_copies_the_score_and_the_first_trigger_from_the_prompt():
    m = generate_match(7)
    case = detect(m, "r1", (1, 300_000))[0]
    draft = Draft.from_dict(json.loads(echo(moment_prompt(case, m))))
    score = next(f for f in case.facts if f["name"] == "score")
    assert draft.text == f"The score is {score['display']}."
    assert [(c.fact_ids, c.event_ids) for c in draft.claims] == [
        ((score["fact_id"],), case.trigger_ids[:1])
    ]
    assert check(draft, case, moment_evidence(m, case)).passed
    with pytest.raises(ScriptExhausted, match="score fact"):
        echo("Moment m7-k1 at clock 00:01.")

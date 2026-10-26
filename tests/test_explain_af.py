"""Spike: Microsoft Agent Framework carries a `MomentCase` through three executors.

The executors are stand-ins (the real Detector, Analyst and Guard are in `explain.workflow`): what
this pins is the framework part alone. A workflow of three executors with a Guard → Analyst back
edge runs on the fake chat client, every handoff lands in the log, a retry sees the previous
reasons, and a case leaves only through the Guard, as a narrative or after the last attempt as
stats-only."""

import asyncio
import json

from agent_framework import Agent, Executor, WorkflowBuilder, WorkflowContext, handler
from agent_framework.exceptions import ChatClientException
from explain_strategies import case

from matchlens.explain.fake import FakeChatClient
from matchlens.explain.log import HandoffLog, Role, read_handoffs
from matchlens.explain.state import (
    MAX_ATTEMPTS,
    Attempt,
    CallError,
    CallFailure,
    Draft,
    MomentCase,
    MomentOutcome,
    Reason,
    Verdict,
)

GOOD = json.dumps(
    {
        "text": "Corrowmere lead.",
        "claims": [
            {"text": "lead", "fact_ids": ["m7/goal"], "event_ids": ["m7-e00412"], "frame_ids": []}
        ],
    }
)
WRONG = json.dumps({"text": "wrong number", "claims": []})


class Detector(Executor):
    def __init__(self, log: HandoffLog) -> None:
        super().__init__(id="moment_detector")
        self.log = log

    @handler
    async def start(self, moment: MomentCase, ctx: WorkflowContext[MomentCase]) -> None:
        self.log.record(Role.DETECTOR, Role.ANALYST, moment)
        await ctx.send_message(moment)


class Analyst(Executor):
    def __init__(self, log: HandoffLog, client: FakeChatClient) -> None:
        super().__init__(id="analyst")
        self.log = log
        self.agent = Agent(client, instructions="Write one sentence. Reply with JSON only.")

    @handler
    async def draft(self, moment: MomentCase, ctx: WorkflowContext[MomentCase]) -> None:
        n = len(moment.attempts) + 1
        reasons = [r.detail for a in moment.attempts for r in a.verdict.reasons]
        prompt = json.dumps({"facts": list(moment.facts), "rejected_because": reasons})
        # the real client wraps every SDK failure in ChatClientException; a ScriptExhausted from
        # the fake is an AssertionError and stops the test instead of becoming a failed attempt
        try:
            reply = await self.agent.run(prompt)
            attempt = Attempt(n, "fake", Draft.from_dict(json.loads(reply.text)))
        except ChatClientException as e:
            attempt = Attempt(n, "fake", None, error=CallFailure(CallError.TRANSPORT, str(e)))
        except ValueError as e:
            failure = CallFailure(CallError.INVALID_REPLY, f"{type(e).__name__}: {e}")
            attempt = Attempt(n, "fake", None, error=failure)
        moment = moment.with_attempt(attempt)
        self.log.record(Role.ANALYST, Role.GUARD, moment)
        await ctx.send_message(moment)


class Guard(Executor):
    def __init__(self, log: HandoffLog) -> None:
        super().__init__(id="guard")
        self.log = log

    @handler
    async def judge(self, moment: MomentCase, ctx: WorkflowContext[MomentCase, MomentCase]) -> None:
        draft = moment.attempts[-1].draft
        if draft is None:
            verdict = Verdict(False, (Reason("no_draft", moment.attempts[-1].error.detail),))
        elif "wrong" in draft.text:
            verdict = Verdict(False, (Reason("number_not_cited", "a number cites no fact"),))
        else:
            verdict = Verdict(True)
        moment = moment.with_verdict(verdict)
        if moment.is_open and len(moment.attempts) < MAX_ATTEMPTS:
            self.log.record(Role.GUARD, Role.ANALYST, moment)
            await ctx.send_message(moment)
            return
        if moment.is_open:
            moment = moment.stats_only()
        self.log.record(Role.GUARD, Role.RENDER, moment)
        await ctx.yield_output(moment)


def run(tmp_path, replies):
    log = HandoffLog(tmp_path / "handoffs.jsonl")
    client = FakeChatClient(replies)
    detector, analyst, guard = Detector(log), Analyst(log, client), Guard(log)
    workflow = (
        WorkflowBuilder(start_executor=detector)
        .add_edge(detector, analyst)
        .add_edge(analyst, guard)
        .add_edge(guard, analyst)
        .build()
    )
    outputs = asyncio.run(workflow.run(case())).get_outputs()
    return outputs, read_handoffs(log.path), client


def route(handoffs):
    return [(h.sender.value, h.receiver.value, len(h.case.attempts)) for h in handoffs]


def test_a_first_draft_that_passes_goes_straight_out(tmp_path):
    outputs, handoffs, client = run(tmp_path, [GOOD])
    assert [o.outcome for o in outputs] == [MomentOutcome.NARRATIVE]
    assert route(handoffs) == [
        ("moment_detector", "analyst", 0),
        ("analyst", "guard", 1),
        ("guard", "render", 1),
    ]
    assert handoffs[-1].case == outputs[0]
    assert outputs[0].attempts[0].draft.claims[0].event_ids == ("m7-e00412",)
    assert len(client.requests) == 1


def test_a_rejected_draft_is_retried_with_the_reasons(tmp_path):
    outputs, handoffs, client = run(tmp_path, [WRONG, WRONG, GOOD])
    assert [o.outcome for o in outputs] == [MomentOutcome.NARRATIVE]
    assert [h.receiver.value for h in handoffs] == [
        *["analyst", "guard"] * MAX_ATTEMPTS,
        "render",
    ]
    messages, options = client.requests[1]
    assert [m.role for m in messages] == ["user"]  # no history of the first attempt leaks in
    assert json.loads(messages[0].text)["rejected_because"] == ["a number cites no fact"]
    assert options["instructions"].startswith("Write one sentence")


def test_after_the_last_rejection_the_case_leaves_stats_only(tmp_path):
    timeout = ChatClientException("Anthropic chat request failed: Request timed out.")
    outputs, handoffs, client = run(tmp_path, ["not json", timeout, WRONG])
    assert [o.outcome for o in outputs] == [MomentOutcome.STATS_ONLY]
    assert outputs[0].narrative is None
    errors = [a.error for a in outputs[0].attempts]
    assert errors[0].code is CallError.INVALID_REPLY and errors[0].detail.startswith("JSONDecode")
    assert errors[1] == CallFailure(CallError.TRANSPORT, str(timeout))
    assert errors[2] is None and not outputs[0].attempts[2].verdict.passed
    assert route(handoffs)[-1] == ("guard", "render", MAX_ATTEMPTS)
    assert len(client.requests) == MAX_ATTEMPTS  # no fourth call

"""The Explain workflow: Moment Detector → Analyst → Guard (→ Persona Editor → Guard) on
Microsoft Agent Framework (and Translator → Guard over a finished run, `explain.translator`).

Three executors in a `WorkflowBuilder` graph with a conditional Guard → Analyst edge for retries,
and with personas (M5) a fourth: the Guard sends a narrative that passed to the Persona Editor
once per persona, judges each rendition like a draft, sends a rejected one back once with its
reasons, and lets the case out when every rendition passed or fell back to the narrative. The
edges' conditions read the case's phase, so the Guard needs no other state.
The Detector sends every moment of the match prefix; the Analyst drafts each (one model call per
attempt); the Guard judges a draft against the engine and sends a rejected case back with its
reasons, at most twice, or lets it out: a narrative that passed, or a stats-only cue made of the
engine's facts. Only the Guard judges (`with_verdict`), and every handoff goes to the run's log.
AF delivers one sender's messages to a receiver in the order they were sent, so the Analyst's
calls come in rounds: every moment's first attempt, then the second attempts of the rejected
ones, and so on, each round in the order the moments end. With personas, the Analyst's retries
and the Persona Editor's attempts may run side by side in one superstep: an attempt reserves its
requests in the budget before it awaits anything, so the cap holds for both agents together, and
one pace spaces them.

Recovery: a call that brings no draft (timeout, a 429, a transport error or a failed facts
tool, a refusal, a reply that is no `Draft`) is an attempt like a rejected draft; the SDK
retries nothing, so every model request is one the budget counts (but the other agent's
attempt in flight when a `FatalCallError` stops the run). After 3
failures in a row that brought no answer at all (timeout, rate limited, transport) the circuit
breaker opens; from then on, or once `max_calls` model calls are spent, the Analyst records a
skipped attempt without a call, which the Guard ends as stats-only at once (an attempt of the
other agent that started before the breaker opened still ends; the cap is never exceeded). A
`FatalCallError` (credentials, a request no retry mends) stops the run, as does a case whose
facts are not the engine's: that is a bug of the pipeline, not a moment to skip, and the
Detector finds it before the first call (it looks up each moment's evidence, which the Guard
then uses). The Persona
Editor shares the Analyst's budget, breaker and pace: `max_calls` counts every agent's requests.
The Guard also judges a closed case's translations (`TranslatorExecutor`): each in its language
against its source, a rejected one back once with its reasons, a second rejection a fallback to
the English text.
"""

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass

from agent_framework import (
    Executor,
    MCPStreamableHTTPTool,
    SupportsChatGetResponse,
    WorkflowBuilder,
    WorkflowContext,
    handler,
)

from matchlens.explain.analyst import FACTS_TOOL, Analyst
from matchlens.explain.detector import detect
from matchlens.explain.guard import Evidence, check, judge, moment_evidence, stats_only_draft
from matchlens.explain.log import HandoffLog, Role
from matchlens.explain.persona import PersonaEditor
from matchlens.explain.state import (
    DEFAULT_MAX_CALLS,
    MAX_ATTEMPTS,
    Attempt,
    CallError,
    CallFailure,
    Draft,
    MomentCase,
    Persona,
)
from matchlens.facts import Time
from matchlens.match import Match

FACTS_TIMEOUT_S = 10  # one MCP request; `facts_at` answers in tens of milliseconds
BREAKER_AFTER = 3  # failures in a row without an answer that open the circuit breaker
_clock, _sleep = time.monotonic, asyncio.sleep  # the pace's clock, replaced in tests
NO_ANSWER = frozenset({CallError.TIMEOUT, CallError.RATE_LIMITED, CallError.TRANSPORT})


class FactsUnavailable(Exception):
    """The MCP server of the facts cannot be reached or does not serve the match: no call made."""


@dataclass(frozen=True)
class Prefix:
    """The workflow's input: the moments that end by `until` (period, clock_ms), None for all."""

    until: Time | None = None


@dataclass(frozen=True)
class Explained:
    """A moment out of the workflow: its closed case and its cue, which is the narrative that
    passed the Guard or the stats-only cue."""

    case: MomentCase
    cue: Draft

    def for_persona(self, persona: Persona | str) -> Draft:
        """What `persona` sees: its rendition that passed, else the cue."""
        return self.case.rendition(persona) or self.cue


@dataclass
class CallBudget:
    """The model requests of one run: at most `max_calls`, none once the breaker is open. An
    attempt may make up to `per_attempt` requests (two with the facts tool; one for the Persona
    Editor), so it starts only when that many are left: `reserve` checks and holds them in one
    step, before the attempt awaits anything, and `count` turns the reservation into the
    requests made. Attempts in flight side by side can therefore never pass the cap."""

    max_calls: int = DEFAULT_MAX_CALLS
    per_attempt: int = 1
    calls: int = 0
    no_answer_in_row: int = 0
    reserved: int = 0  # requests held by attempts in flight

    def __post_init__(self) -> None:
        if type(self.max_calls) is not int or self.max_calls < 0:
            raise ValueError(f"max_calls = {self.max_calls!r} is not an int of at least 0")
        if type(self.per_attempt) is not int or self.per_attempt < 1:
            raise ValueError(f"per_attempt = {self.per_attempt!r} is not an int of at least 1")

    def _need(self, need: int | None) -> int:
        return self.per_attempt if need is None else min(need, self.per_attempt)

    def why_not(self, need: int | None = None) -> str | None:
        """Why the next attempt, of up to `need` requests (`per_attempt` if None), may make no
        call, or None when it may; the requests held by attempts in flight count as spent."""
        need = self._need(need)
        if self.no_answer_in_row >= BREAKER_AFTER:
            return f"circuit breaker open after {BREAKER_AFTER} calls in a row without an answer"
        if self.calls + self.reserved + need > self.max_calls:
            held = f" or held by attempts in flight ({self.reserved})" if self.reserved else ""
            return f"the run's {self.max_calls} model calls are spent{held}"
        return None

    def reserve(self, need: int | None = None) -> str | None:
        """`why_not`, and when the attempt may call, its `need` requests held for it: one
        synchronous step, so two attempts never both take the last requests."""
        if (why := self.why_not(need)) is None:
            self.reserved += self._need(need)
        return why

    def count(self, attempt: Attempt, reserved: int = 0) -> None:
        """The requests `attempt` made, in place of the `reserved` ones held for it by `reserve`
        (the same `need`, capped alike); without a reservation, up to `per_attempt`."""
        held = self._need(reserved) if reserved else 0
        if held > self.reserved:
            raise RuntimeError(f"an attempt releases {held} requests, {self.reserved} are held")
        if attempt.requests > (held or self.per_attempt):  # fail closed: the cap would not hold
            raise RuntimeError(f"an attempt made {attempt.requests} model requests")
        self.reserved -= held
        self.calls += attempt.requests
        failed = attempt.error is not None and attempt.error.code in NO_ANSWER
        self.no_answer_in_row = self.no_answer_in_row + 1 if failed else 0


class Pace:
    """Spaces the model attempts of a run, every agent's: an attempt starts no sooner than
    `pace_s` seconds after the previous one, so a run stays under the deployment's tokens per
    minute (the SDK retries no 429). Attempts of two agents in one superstep wait in turn."""

    def __init__(self, pace_s: float = 0.0) -> None:
        self.pace_s = pace_s
        self._last_start: float | None = None
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            if self._last_start is not None:
                await _sleep(self._last_start + self.pace_s - _clock())
            self._last_start = _clock()


class DetectorExecutor(Executor):
    def __init__(
        self, match: Match, run_id: str, log: HandoffLog, evidence: dict[str, Evidence]
    ) -> None:
        super().__init__(id=Role.DETECTOR.value)
        self.match, self.run_id, self.log, self.evidence = match, run_id, log, evidence

    @handler
    async def start(self, prefix: Prefix, ctx: WorkflowContext[MomentCase]) -> None:
        cases = detect(self.match, self.run_id, prefix.until)
        for case in cases:  # every case is checked against the engine before any call
            self.evidence[case.moment_id] = moment_evidence(self.match, case)
        for case in cases:
            self.log.record(Role.DETECTOR, Role.ANALYST, case)
            await ctx.send_message(case)


class AnalystExecutor(Executor):
    """Drafts each case, within the run's budget and pace. `role`: the writer it is in the log,
    the Analyst or (with a `RecapWriter`) the Recap Writer."""

    def __init__(
        self,
        analyst: Analyst,
        budget: CallBudget,
        log: HandoffLog,
        pace: Pace | float = 0.0,
        role: Role = Role.ANALYST,
    ) -> None:
        super().__init__(id=role.value)
        self.analyst, self.budget, self.log, self.role = analyst, budget, log, role
        self.pace = pace if isinstance(pace, Pace) else Pace(pace)

    @handler
    async def draft(self, case: MomentCase, ctx: WorkflowContext[MomentCase]) -> None:
        need = self.analyst.max_requests
        if (why := self.budget.reserve(need)) is not None:  # before any await
            skipped = CallFailure(CallError.SKIPPED, why)
            attempt = Attempt(len(case.attempts) + 1, self.analyst.model, None, error=skipped)
        else:
            await self.pace.wait()
            attempt = await self.analyst.attempt(case)  # a FatalCallError stops the run
            self.budget.count(attempt, need)
        case = case.with_attempt(attempt)
        self.log.record(self.role, Role.GUARD, case)
        await ctx.send_message(case)


class PersonaExecutor(Executor):
    """Writes each case's pending rendition, within the run's budget and pace."""

    def __init__(
        self, editor: PersonaEditor, budget: CallBudget, log: HandoffLog, pace: Pace
    ) -> None:
        super().__init__(id=Role.PERSONA_EDITOR.value)
        self.editor, self.budget, self.log, self.pace = editor, budget, log, pace

    @handler
    async def rewrite(self, case: MomentCase, ctx: WorkflowContext[MomentCase]) -> None:
        rendition = case.pending_rendition
        n = len(rendition.attempts) + 1
        need = self.editor.max_requests
        if (why := self.budget.reserve(need)) is not None:  # before any await
            skipped = CallFailure(CallError.SKIPPED, why)
            attempt = Attempt(n, self.editor.model, None, error=skipped)
        else:
            await self.pace.wait()
            attempt = await self.editor.attempt(case, rendition)  # a FatalCallError stops it
            self.budget.count(attempt, need)
        case = case.with_rendition(rendition.with_attempt(attempt))
        self.log.record(Role.PERSONA_EDITOR, Role.GUARD, case)
        await ctx.send_message(case)


class TranslatorExecutor(Executor):
    """Writes each case's pending translation, within the run's budget and pace. `translator`: a
    `explain.translator.Translator` (or anything with its `attempt`, `model`, `max_requests`)."""

    def __init__(self, translator, budget: CallBudget, log: HandoffLog, pace: Pace) -> None:
        super().__init__(id=Role.TRANSLATOR.value)
        self.translator, self.budget, self.log, self.pace = translator, budget, log, pace

    @handler
    async def translate(self, case: MomentCase, ctx: WorkflowContext[MomentCase]) -> None:
        translation = case.pending_translation
        n = len(translation.attempts) + 1
        need = self.translator.max_requests
        if (why := self.budget.reserve(need)) is not None:  # before any await
            skipped = CallFailure(CallError.SKIPPED, why)
            attempt = Attempt(n, self.translator.model, None, error=skipped)
        else:
            await self.pace.wait()
            attempt = await self.translator.attempt(case, translation)  # a FatalCallError stops it
            self.budget.count(attempt, need)
        case = case.with_translation(translation.with_attempt(attempt))
        self.log.record(Role.TRANSLATOR, Role.GUARD, case)
        await ctx.send_message(case)


class GuardExecutor(Executor):
    """Judges every attempt. `writer`: who drafts the cases (the Analyst, or the Recap Writer);
    `fallback`: the cue of a case no draft passed, made of the engine's facts (None: the
    stats-only cue)."""

    def __init__(
        self,
        log: HandoffLog,
        evidence: dict[str, Evidence],
        personas: tuple[Persona, ...] = (),
        writer: Role = Role.ANALYST,
        fallback: Callable[[MomentCase, Evidence], Draft] | None = None,
    ) -> None:
        super().__init__(id=Role.GUARD.value)
        self.log, self.evidence = log, evidence  # by moment, from the Detector
        self.personas, self.writer, self.fallback = personas, writer, fallback

    @handler
    async def review(self, case: MomentCase, ctx: WorkflowContext[MomentCase, Explained]) -> None:
        evidence = self.evidence[case.moment_id]
        if case.is_open:  # the Analyst's attempt
            case = case.with_verdict(judge(case, evidence))
            last = case.attempts[-1]
            if case.is_open and len(case.attempts) < MAX_ATTEMPTS and last.called_model:
                self.log.record(Role.GUARD, self.writer, case)
                await ctx.send_message(case)
                return
            if case.is_open:
                case = case.stats_only()
            elif self.personas:
                case = case.with_personas(self.personas)
        elif case.pending_rendition is not None:  # the Persona Editor's attempt at it
            rendition = case.pending_rendition.with_verdict(judge(case, evidence))
            if rendition.is_open and not rendition.can_retry:
                rendition = rendition.fallback()  # the narrative, which passed, stands in
            case = case.with_rendition(rendition)
        else:  # the Translator's attempt at the pending translation
            translation = case.pending_translation.with_verdict(judge(case, evidence))
            if translation.is_open and not translation.can_retry:
                translation = translation.fallback()  # the English text, which passed, stands in
            case = case.with_translation(translation)
        if case.pending_rendition is not None:  # a rendition to write, or to write again
            self.log.record(Role.GUARD, Role.PERSONA_EDITOR, case)
            await ctx.send_message(case)
            return
        if case.pending_translation is not None:  # a translation to write, or to write again
            self.log.record(Role.GUARD, Role.TRANSLATOR, case)
            await ctx.send_message(case)
            return
        del self.evidence[case.moment_id]
        cue = case.narrative or facts_only_cue(case, evidence, self.fallback)
        self.log.record(Role.GUARD, Role.RENDER, case)
        await ctx.yield_output(Explained(case, cue))


def facts_only_cue(
    case: MomentCase,
    evidence: Evidence,
    fallback: Callable[[MomentCase, Evidence], Draft] | None = None,
) -> Draft:
    """The cue made of the engine's facts (`fallback`, else the stats-only cue); it passes the
    Guard by construction, checked anyway."""
    cue = (fallback or stats_only_draft)(case, evidence)
    if not (verdict := check(cue, case, evidence)).passed:
        codes = ", ".join(r.code for r in verdict.reasons)
        raise RuntimeError(
            f"moment {case.moment_id!r}: its stats-only cue fails the Guard: {codes}"
        )
    return cue


async def explain(
    match: Match,
    client: SupportsChatGetResponse,
    log: HandoffLog,
    *,
    run_id: str,
    until: Time | None = None,
    max_calls: int = DEFAULT_MAX_CALLS,
    facts_url: str | None = None,
    pace_s: float = 0.0,
    personas: tuple[Persona | str, ...] = (),
) -> list[Explained]:
    """Run the workflow on the moments of `match` that end by `until`; every handoff goes to
    `log`. With `facts_url` (a `matchlens mcp --http` server that serves the match) the Analyst
    reads each moment's facts over MCP; `pace_s` spaces the attempts that call the model; each
    of `personas` gets a rendition of every narrative. The moments come out in the order they
    end."""
    personas = tuple(dict.fromkeys(Persona(p) for p in personas))
    async with contextlib.AsyncExitStack() as stack:
        tool = None
        if facts_url is not None:
            tool = MCPStreamableHTTPTool(
                name="matchlens",
                url=facts_url,
                allowed_tools=[FACTS_TOOL],
                approval_mode="never_require",
                request_timeout=FACTS_TIMEOUT_S,
            )
            try:
                await stack.enter_async_context(tool)
                await _check_served(tool, match.meta.match_id, facts_url)
            except Exception as e:  # no server, another protocol, or not this match
                raise FactsUnavailable(f"facts over MCP at {facts_url}: {e}") from e
        analyst = Analyst(client, match, facts_tool=tool)
        budget, evidence, pace = CallBudget(max_calls, analyst.max_requests), {}, Pace(pace_s)
        detector = DetectorExecutor(match, run_id, log, evidence)
        drafter = AnalystExecutor(analyst, budget, log, pace)
        guard = GuardExecutor(log, evidence, personas)
        builder = (
            WorkflowBuilder(start_executor=detector)
            .add_edge(detector, drafter)
            .add_edge(drafter, guard)
            .add_edge(guard, drafter, condition=lambda case: case.is_open)  # a retry, not a cue
        )
        if personas:
            editor = PersonaExecutor(PersonaEditor(client, match), budget, log, pace)
            due = lambda case: not case.is_open and case.pending_rendition is not None  # noqa: E731
            builder = builder.add_edge(guard, editor, condition=due).add_edge(editor, guard)
        workflow = builder.build()
        result = await workflow.run(Prefix(until))
    return sorted(
        result.get_outputs(), key=lambda e: (e.case.period, e.case.end_ms, e.case.moment_id)
    )


async def _check_served(tool: MCPStreamableHTTPTool, match_id: str, url: str) -> None:
    """Before any model call: the server knows the match."""
    listed = await tool.session.call_tool("list_matches", {})
    served = [m["match_id"] for m in (listed.structuredContent or {}).get("result", [])]
    if match_id not in served:
        raise ValueError(f"the MCP server at {url} serves {served}, not {match_id}")

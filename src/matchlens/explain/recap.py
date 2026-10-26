"""The Recap Writer: an LLM agent that writes a match's recap at full time, behind the Guard.

At full time the studio sums the match up (rules 4.1(iii)): how it was decided and why. The recap
is a `MomentCase` with the id `RECAP_ID` (`explain.fulltime`), so it shares the moments' state,
handoff log, summary and Persona Editor: its triggers are the final whistle and every goal, its
facts the whole match's (`guard.recap_evidence`: score, possession, passing, momentum, the flow
of play and their readings, and each goal's minute and the score it made). It must state the
final score. The Recap Writer reads them, the clubs,
the lineups and the key moments' narratives of the run (context only, never cited), and writes
3 to 5 sentences as a `Draft` under the Analyst's rules (`analyst.RULES`). The Guard judges it
against the engine like a moment's draft, with `RECAP_MAX_TEXT` characters at most; a rejected
recap goes back with the reasons, at most twice, then the deterministic recap made of the facts
stands in (`fallback_recap`: score, scorers with their minutes, possession, pass completion and
the flow of play). A recap that passed gets a rendition per persona like a narrative.

Workflow: Detector → Recap Writer → Guard (→ Recap Writer: a retry) (→ Persona Editor → Guard)
→ render, the same executors as the moments' (`explain.workflow`), one model request per attempt,
the run's budget and pace for both agents.
"""

import functools
import json
from collections.abc import Sequence

from agent_framework import Executor as AFExecutor
from agent_framework import SupportsChatGetResponse, WorkflowBuilder, WorkflowContext, handler

from matchlens.explain.analyst import (
    CALL_TIMEOUT_S,
    RULES,
    Scene,
    _Requests,
    agent,
    ask,
    attempt_lines,
)
from matchlens.explain.fulltime import fallback_recap, recap_case, recap_fact_lines
from matchlens.explain.guard import RECAP_MAX_TEXT, recap_evidence
from matchlens.explain.log import HandoffLog, Role
from matchlens.explain.persona import PersonaEditor
from matchlens.explain.state import (
    DEFAULT_MAX_CALLS,
    MAX_ATTEMPTS,
    RECAP_ID,
    Attempt,
    MomentCase,
    Persona,
)
from matchlens.explain.workflow import (
    AnalystExecutor,
    CallBudget,
    Explained,
    GuardExecutor,
    Pace,
    PersonaExecutor,
)
from matchlens.facts import Fact, match_facts
from matchlens.match import Match

RECAP_ROLE = f"""\
You are the Recap Writer of a live broadcast overlay for a fictional football match. At full \
time you write the match's recap: 3 to 5 short sentences in English, at most {RECAP_MAX_TEXT} \
characters (a stricter limit than the one below), and list the claims it is made of. Start with \
the final score, citing the score fact of the whole match: the home club, the score, the away \
club ("Quarrendale Rovers 1–4 Saltreach FC"), the one place a club may follow a score. Then say \
how the match was decided (who scored and when) and why it went that way: use the readings of \
the whole match (possession, momentum, the flow of play) next to the numbers. Never put the \
result into words of your own ("beat", "win", "lose", "loss", "draw", "tie", "the points"): the \
score and the readings say it. Write a goal's minute as its "write as" shows it (5'); a fact of \
a goal's instant tells that instant, never the final score, and never shares a claim with a \
reading of the whole match: two times, two claims. The key moments as the Analyst \
wrote them are listed for context only: every number and phrase you write comes from the facts \
listed and is cited. Every claim cites at least one trigger event: the final whistle, or the \
goal it is about. A deterministic Guard checks the draft against the stats engine and rejects \
it on any breach of the rules below."""
INSTRUCTIONS = f"{RECAP_ROLE}\n\n{RULES}"


def recap_prompt(case: MomentCase, match: Match, narratives: Sequence[MomentCase] = ()) -> str:
    """What the Recap Writer reads: the clubs, lineups and triggers, the facts it may cite (a
    goal's facts named by the goal they are of), the run's narratives and its earlier attempts.
    Nothing is computed here."""
    if not case.is_recap:
        raise ValueError(f"moment {case.moment_id!r} is no recap")
    lines = [
        f"Recap of match {case.match_id} at clock {case.display_clock} (full time).",
        *Scene(case, match).lines(),
        "Facts (fact_id | write as | what it counts | when):",
        *recap_fact_lines(case, match),
    ]
    if narratives:
        lines.append("Key moments as the Analyst wrote them (context only, never cite them):")
        lines += [
            f"- {n.display_clock}: {json.dumps(n.narrative.text, ensure_ascii=False)}"
            for n in narratives
            if n.narrative is not None
        ]
    if case.attempts:
        lines.append("Earlier attempts, all rejected:")
    lines += attempt_lines(case.attempts)
    return "\n".join(lines)


class RecapWriter:
    """Writes one `Attempt` at a recap per call of `attempt`, over any AF chat client (Foundry
    or fake): one model request per attempt, no tool. `narratives`: the run's moments that
    ended as a narrative, as context."""

    max_requests = 1

    def __init__(
        self,
        client: SupportsChatGetResponse,
        match: Match,
        narratives: Sequence[MomentCase] = (),
        *,
        timeout_s: float = CALL_TIMEOUT_S,
    ) -> None:
        self.match, self.narratives = match, tuple(narratives)
        self.model = getattr(client, "model", None) or type(client).__name__
        self.timeout_s = timeout_s
        self._requests = _Requests()
        self.agent = agent(
            client, INSTRUCTIONS, Role.RECAP_WRITER.value, middleware=[self._requests]
        )

    async def attempt(self, case: MomentCase) -> Attempt:
        """The next attempt at the recap: a draft, or the reason the call brought none. A case
        that is no open recap or takes no further attempt is refused before the call."""
        if not case.is_recap:
            raise ValueError(f"moment {case.moment_id!r} is no recap")
        if not case.is_open or len(case.attempts) >= MAX_ATTEMPTS:
            raise ValueError("the recap takes no further attempt")
        if case.attempts and case.attempts[-1].verdict is None:
            raise ValueError("the recap's last attempt is not judged yet")
        prompt = recap_prompt(case, self.match, self.narratives)
        return await ask(self.agent, self._requests, prompt, len(case.attempts) + 1, self.timeout_s)


class _Start(AFExecutor):
    """Opens the recap at the final whistle: the Detector's handoff to the Recap Writer."""

    def __init__(self, log: HandoffLog) -> None:
        super().__init__(id=Role.DETECTOR.value)
        self.log = log

    @handler
    async def start(self, case: MomentCase, ctx: WorkflowContext[MomentCase]) -> None:
        self.log.record(Role.DETECTOR, Role.RECAP_WRITER, case)
        await ctx.send_message(case)


async def write_recap(
    match: Match,
    client: SupportsChatGetResponse,
    log: HandoffLog,
    *,
    run_id: str,
    narratives: Sequence[MomentCase] = (),
    max_calls: int = DEFAULT_MAX_CALLS,
    pace_s: float = 0.0,
    personas: tuple[Persona | str, ...] = (),
    whole: Sequence[Fact] | None = None,
) -> Explained:
    """Write `match`'s recap with the agents; every handoff goes to `log`. `narratives`: the
    run's moments (context); `whole`: the match's `match_facts`, if already computed. The recap
    that comes out passed the Guard, or is the deterministic one; each of `personas` gets a
    rendition of a recap that passed."""
    personas = tuple(dict.fromkeys(Persona(p) for p in personas))
    whole = match_facts(match) if whole is None else whole
    case = recap_case(match, run_id, whole)
    evidence = {RECAP_ID: recap_evidence(match, case, whole)}  # checks the case before any call
    writer = RecapWriter(client, match, [n for n in narratives if n.narrative is not None])
    budget, pace = CallBudget(max_calls, writer.max_requests), Pace(pace_s)
    start = _Start(log)
    drafter = AnalystExecutor(writer, budget, log, pace, role=Role.RECAP_WRITER)
    fallback = functools.partial(fallback_recap, match)
    guard = GuardExecutor(log, evidence, personas, writer=Role.RECAP_WRITER, fallback=fallback)
    builder = (
        WorkflowBuilder(start_executor=start)
        .add_edge(start, drafter)
        .add_edge(drafter, guard)
        .add_edge(guard, drafter, condition=lambda c: c.is_open)  # a retry
    )
    if personas:
        editor = PersonaExecutor(PersonaEditor(client, match), budget, log, pace)
        due = lambda c: not c.is_open and c.pending_rendition is not None  # noqa: E731
        builder = builder.add_edge(guard, editor, condition=due).add_edge(editor, guard)
    result = await builder.build().run(case)
    (out,) = result.get_outputs()
    return out

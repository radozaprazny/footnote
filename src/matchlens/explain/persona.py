"""The Persona Editor: an LLM agent that rewrites a narrative that passed the Guard for a persona.

The same verified moment reaches a data-hungry analyst and a casual fan as two different
captions (rules 4.1(e)): the analyst reads the Analyst's narrative as it is, the fan a
rendition of it. The Persona Editor sees the narrative and its claims, the facts they cite and
the moment's readings, and writes a `Draft` for the persona under the same rules as the Analyst
(`analyst.RULES`); the Guard judges it with the same `check`, against the engine, never trusting
the editor's copies. It computes nothing and adds nothing: a sentence it cannot back with a
cited fact or reading fails the Guard, and a rendition that fails twice falls back to the
narrative. One model request per attempt, no tool: the facts it may cite are in the prompt.
"""

import json

from agent_framework import SupportsChatGetResponse

from matchlens.explain.analyst import (
    CALL_TIMEOUT_S,
    RULES,
    Scene,
    _Requests,
    agent,
    ask,
    attempt_lines,
    draft_lines,
)
from matchlens.explain.fulltime import final_score_id, recap_fact_lines
from matchlens.explain.state import (
    PERSONA_ATTEMPTS,
    Attempt,
    MomentCase,
    Persona,
    Rendition,
)
from matchlens.match import Match

ROLES = {
    Persona.FAN: """\
You are the Persona Editor of a live broadcast overlay for a fictional football match. A caption \
written for analysts has passed the Guard; you rewrite it for a casual fan watching on a phone: \
one or two short sentences in plain English, at most 2 numbers, a reading's phrase rather than a \
percentage where the moment has one, the names as given. A claim that uses a reading's phrase \
cites that reading and needs no number. Make it plainly different from the caption, never a \
copy: drop the clock time, every percentage and every shirt number, keep the score, and if the \
caption already reads that way, keep only its most important sentence. Keep only what the \
caption and the facts below say, and add nothing: no word of praise or blame of your own. A \
deterministic Guard checks your draft against the stats engine with the rules below, exactly \
as it checked the caption.""",
}
INSTRUCTIONS = {persona: f"{role}\n\n{RULES}" for persona, role in ROLES.items()}
# always offered, with the caption's facts: the moment's time and score, which the Guard's
# evidence holds, so a fan's line may say when and where the game stands
SCENE_FACTS = frozenset({"clock", "minute", "score"})


def persona_prompt(case: MomentCase, rendition: Rendition, match: Match) -> str:
    """What the Persona Editor reads: the moment, the caption that passed and its claims, the
    facts it may cite (the caption's, the moment's readings, clock, minute and score) and the
    rendition's earlier attempts. Nothing is computed here."""
    narrative = case.narrative
    if narrative is None:
        raise ValueError(f"moment {case.moment_id!r} has no narrative to rewrite")
    scene = Scene(case, match)
    cited = {f for c in narrative.claims for f in c.fact_ids}
    final = final_score_id(case.match_id)
    facts = [
        f
        for f in case.facts
        if f["fact_id"] in cited
        or str(f.get("name", "")).endswith("_reading")
        or (case.is_recap and f["fact_id"] == final)
        or (
            not case.is_recap
            and f.get("name") in SCENE_FACTS
            and f["fact_id"].split("/")[2][:3] in ("at-", "to-")
        )
    ]
    lines = [
        f"Persona {rendition.persona.value} for moment {case.moment_id} at clock "
        f"{case.display_clock}.",
        *scene.lines(),
        f"The caption that passed the Guard: {json.dumps(narrative.text, ensure_ascii=False)}",
        *draft_lines(narrative),
    ]
    if case.is_recap:  # a goal's facts tell its instant; the final score must stay
        lines += [
            f"The caption is the match's recap at full time: keep its final score (the fact "
            f"{final}) and cite it; a fact of a goal's instant is no final score and never "
            "shares a claim with a reading of the whole match.",
            "Facts you may cite (fact_id | write as | what it counts | when):",
            *recap_fact_lines(case, match, facts),
        ]
    else:
        lines += [
            "Facts you may cite (fact_id | write as | what it counts | window):",
            *scene.fact_lines(facts),
        ]
    lines.append(f"Caption JSON: {json.dumps(narrative.to_dict(), ensure_ascii=False)}")
    if rendition.attempts:
        lines.append("Earlier attempts, all rejected:")
    lines += attempt_lines(rendition.attempts)
    return "\n".join(lines)


class PersonaEditor:
    """Writes one `Attempt` at a rendition per call of `attempt`, over any AF chat client (the
    Analyst's, Foundry or fake): one agent per persona, one model request per attempt."""

    max_requests = 1

    def __init__(
        self, client: SupportsChatGetResponse, match: Match, *, timeout_s: float = CALL_TIMEOUT_S
    ) -> None:
        self.match = match
        self.model = getattr(client, "model", None) or type(client).__name__
        self.timeout_s = timeout_s
        self._requests = _Requests()
        self.agents = {
            p: agent(
                client, INSTRUCTIONS[p], f"persona_editor_{p.value}", middleware=[self._requests]
            )
            for p in Persona
        }

    async def attempt(self, case: MomentCase, rendition: Rendition) -> Attempt:
        """The next attempt at `rendition` of `case`: a draft, or the reason the call brought
        none. A rendition that takes no further attempt is refused before the (billed) call."""
        if not rendition.is_open or len(rendition.attempts) >= PERSONA_ATTEMPTS:
            raise ValueError(f"rendition {rendition.persona.value!r} takes no further attempt")
        if rendition.attempts and rendition.attempts[-1].verdict is None:
            raise ValueError(f"rendition {rendition.persona.value!r}: last attempt not judged")
        prompt = persona_prompt(case, rendition, self.match)
        writer = self.agents[rendition.persona]
        return await ask(
            writer, self._requests, prompt, len(rendition.attempts) + 1, self.timeout_s
        )

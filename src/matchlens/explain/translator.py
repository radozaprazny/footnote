"""The Translator: an LLM agent that translates a text that passed the Guard, behind the Guard.

The same verified moment reaches a viewer who reads Slovak (rules 4.1(vi)): each text a persona
reads that the agents wrote, the Analyst's narrative and a persona's own rendition (and the
recap's), gets a translation per language (`MomentCase.with_translations`). The Translator sees
the English text and its claims, the facts they cite with how to write them in the target
language (a reading as its phrase there, `stats.readings.PHRASES`), and writes a `Draft` in that
language with the same claims and citations. It computes nothing and adds nothing: the Guard
judges the draft in that language against the engine, as it judged the source, and against the
source itself, whose every numeral and name it must keep byte for byte (`guard.check` with
`source`). A translation that fails twice falls back to the English text, which passed. One model
request per attempt, no tool.

Workflow over a finished run (`translate`): the run's closed narratives (moments and recap) go
from the Guard to the Translator, back to the Guard, again to the Translator with the reasons
(one retry) or for the next translation, and out to render once every translation is closed;
one budget and one pace for every attempt. Each further language costs its phrases in
`PHRASES`, its `guard.Language` (number words, judgements, window, shirt context), its fact-cue
templates and a run.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass

from agent_framework import Executor as AFExecutor
from agent_framework import SupportsChatGetResponse, WorkflowBuilder, WorkflowContext, handler

from matchlens.explain.analyst import (
    CALL_TIMEOUT_S,
    Scene,
    _Requests,
    agent,
    ask,
    attempt_lines,
    draft_lines,
    window,
)
from matchlens.explain.guard import (
    LANGUAGES,
    MAX_CLAIMS,
    MAX_TEXT,
    RECAP_MAX_TEXT,
    TRANSLATION_SLACK,
    Evidence,
    moment_evidence,
    recap_evidence,
)
from matchlens.explain.log import HandoffLog, Role
from matchlens.explain.state import (
    ANALYST,
    DEFAULT_MAX_CALLS,
    TRANSLATION_ATTEMPTS,
    Attempt,
    Lang,
    MomentCase,
    Translation,
)
from matchlens.explain.workflow import (
    CallBudget,
    Explained,
    GuardExecutor,
    Pace,
    TranslatorExecutor,
)
from matchlens.facts import Fact, match_facts
from matchlens.match import Match

LANGUAGE_NAMES = {Lang.SK: "Slovak"}
TRANSLATOR_ROLE = """\
You are the Translator of a live broadcast overlay for a fictional football match. A text in \
English has passed the Guard; you translate it into {language} for viewers who read {language}: \
natural {language}, sentence by sentence, the same claims in the same order, nothing added and \
nothing left out. A deterministic Guard checks your translation against the stats engine and \
against the English text with the rules below."""
# the rules of a translation into Slovak: the Guard checks each of them (`guard.SLOVAK`)
RULES_SK = f"""\
Numbers
- Copy every numeral of the English text byte for byte, as often as it has it: 57%, 1–0, \
67:23, 5', 45+2', 12.7 km, 108 km/h stay exactly as written: no "57 %", no "12,7", no "68. \
minúta", no other dash. Add no numeral and drop none.
- Never write a number in words, in any form: no "nula", "jeden", "jedna", "jedno", "dva", \
"dve", "tri", "päť", "dvakrát", "prvý", "druhý", "tretí", "polovica", "pol", "pár", "len raz". \
Reword without it.
- A fact of the window "last 5 minutes" needs "posledných 5 minút" (or "v posledných 5 \
minútach") in its claim. A shirt number "No. 7" becomes "č. 7". A unit stays right after its \
number.

Readings
- Where the English text has a reading's phrase, write that reading's Slovak phrase from \
"write as" below word for word, never in another form ("vyrovnáva", never "vyrovnal" or \
"vyrovnanie"; "vo vedení", never "vedie"), in the claim that cites the reading, with its club \
named right before it and no other club or player name in between. The phrases of momentum, \
flow and possession follow a verb: "Corrowmere má navrch", "Corrowmere je pod tlakom", \
"Saltreach FC a Corrowmere hrajú vyrovnane", "Vellbridge Town má viac lopty", "je to otvorená \
hra".
- No other words judge the score or the play, in any form, with "ne-" too: no "vedie", "vedenie", \
"vyrovnanie", "remíza", "remizovať", "zremizovať", "nerozhodne", "náskok", "znížil", "vyhrať", \
"zvíťaziť", "výhra", "víťazstvo", "prehrať", "prehra", "poraziť", "neporazený", "zdolať", \
"dominovať", "prevaha", "pod kontrolou", "kontrolovať hru", "lepší tím", "chaotický", "pokojný", \
"otvoriť skóre", "úvodný gól", "zaostávať", "je vzadu", "obrat", "bezgólový", "body", and no \
"viac", "menej" or "najviac" near "lopty", "držania", "striel", "prihrávok" or "šancí" outside a \
phrase. A player may still win the ball: "vyhrá loptu", "vyhrá hlavičkový súboj", "súboj o loptu" \
(but no "vyhráva súboj" alone); "pokojne zakončil" and "strieľa z prvej" are fine.
- A reading of the last 5 minutes goes into a claim with "posledných 5 minút", any other \
reading into a claim without it and without other words for a time ("nedávno", "v tejto \
fáze", "v poslednom čase", "polčas", "po prestávke").

Names
- Write every club and player name exactly as given, never declined: "Darnell Fenwright", never \
"Darnella Fenwrighta"; "Vellbridge Town", never "Vellbridge Townu". Put a name where it needs no \
ending: as the subject, or after a noun that takes the case instead ("hráč Darnell Fenwright", \
"strela hráča Darnell Fenwright", "tím Vellbridge Town", "brankár Cian Mulvarra").
- Keep every name of the English text and add none. Words that are no names are lower case \
unless they start a sentence. No colon as punctuation (a clock such as 67:23 is fine).

Claims
- One claim for each claim of the English text, in the same order, citing exactly its \
fact_ids, event_ids and frame_ids. Its text is the Slovak of that clause, copied character for \
character into the translation, so that it appears there word for word. Every numeral lies \
inside a claim.
- At most {MAX_CLAIMS} claims and {int(MAX_TEXT * TRANSLATION_SLACK)} characters \
({int(RECAP_MAX_TEXT * TRANSLATION_SLACK)} for a recap).

Retries
- If earlier attempts are listed, each failed for the reasons given; a reason tagged [claim i] \
is about claim i of that attempt. Write a new translation that fixes every reason.

Reply with the JSON object only."""
RULES = {Lang.SK: RULES_SK}
INSTRUCTIONS = {
    lang: f"{TRANSLATOR_ROLE.format(language=LANGUAGE_NAMES[lang])}\n\n{RULES[lang]}"
    for lang in Lang
}
_WHOSE = {ANALYST: "the analyst's caption"}


def translation_prompt(case: MomentCase, translation: Translation, match: Match) -> str:
    """What the Translator reads: the moment, the English text that passed and its claims, the
    facts they cite with how to write them in the target language, and the translation's earlier
    attempts. Nothing is computed here."""
    source = case.source(translation)
    scene = Scene(case, match)
    language = LANGUAGES[translation.lang.value]
    whose = _WHOSE.get(translation.persona, f"the {translation.persona}'s rendition")
    if case.is_recap:
        whose = f"{whose} of the match's recap at full time"
    cited = {f for c in source.claims for f in c.fact_ids}
    lines = [
        f"Translation into {translation.lang.value} of {translation.persona} for moment "
        f"{case.moment_id} at clock {case.display_clock}.",
        *scene.lines(),
        f"The English text that passed the Guard, {whose}: "
        f"{json.dumps(source.text, ensure_ascii=False)}",
        *draft_lines(source),
        "Facts it cites (fact_id | write as | what it counts | window):",
    ]
    for f in case.facts:
        if f["fact_id"] in cited:
            name = str(f.get("name", "")).replace("_", " ")
            lines.append(
                f"- {f['fact_id']} | {write_in(f, language.phrases)} | {name} of "
                f"{scene.who(f.get('team'), f.get('player'))} | {window(f['fact_id'])}"
            )
    lines.append(f"Source JSON: {json.dumps(source.to_dict(), ensure_ascii=False)}")
    if translation.attempts:
        lines.append("Earlier attempts, all rejected:")
    lines += attempt_lines(translation.attempts)
    return "\n".join(lines)


def write_in(fact: dict, phrases: dict[str, str]) -> str:
    """How a translation writes a fact: a reading as its phrase in the language, a shirt number
    as `č. 7`, anything else as its display (and its unit)."""
    display, unit = fact["display"], fact.get("unit")
    if str(fact.get("name", "")).endswith("_reading"):
        return phrases.get(str(fact.get("value")), display)
    if fact.get("name") == "shirt_number":
        return f"č. {display}"
    return f"{display} {unit}" if unit and unit not in display else display


class Translator:
    """Writes one `Attempt` at a translation per call of `attempt`, over any AF chat client
    (Foundry or fake): one agent per language, one model request per attempt."""

    max_requests = 1

    def __init__(
        self, client: SupportsChatGetResponse, match: Match, *, timeout_s: float = CALL_TIMEOUT_S
    ) -> None:
        self.match = match
        self.model = getattr(client, "model", None) or type(client).__name__
        self.timeout_s = timeout_s
        self._requests = _Requests()
        self.agents = {
            lang: agent(
                client, INSTRUCTIONS[lang], f"translator_{lang.value}", middleware=[self._requests]
            )
            for lang in Lang
        }

    async def attempt(self, case: MomentCase, translation: Translation) -> Attempt:
        """The next attempt at `translation` of `case`: a draft, or the reason the call brought
        none. A translation that takes no further attempt is refused before the (billed) call."""
        what = translation.what
        if not translation.is_open or len(translation.attempts) >= TRANSLATION_ATTEMPTS:
            raise ValueError(f"{what} takes no further attempt")
        if translation.attempts and translation.attempts[-1].verdict is None:
            raise ValueError(f"{what}: last attempt not judged")
        prompt = translation_prompt(case, translation, self.match)
        writer = self.agents[translation.lang]
        n = len(translation.attempts) + 1
        return await ask(writer, self._requests, prompt, n, self.timeout_s)


@dataclass(frozen=True)
class Closed:
    """The workflow's input: a finished run's closed cases, their translations to write."""

    cases: tuple[MomentCase, ...]


class _Start(AFExecutor):
    """Hands each closed case of the run to the Translator, as the Guard does: its first line."""

    def __init__(self, log: HandoffLog) -> None:
        super().__init__(id="translation_desk")
        self.log = log

    @handler
    async def start(self, closed: Closed, ctx: WorkflowContext[MomentCase]) -> None:
        for case in closed.cases:
            self.log.record(Role.GUARD, Role.TRANSLATOR, case)
            await ctx.send_message(case)


async def translate(
    match: Match,
    client: SupportsChatGetResponse,
    log: HandoffLog,
    cases: Sequence[MomentCase],
    *,
    langs: Sequence[Lang | str],
    max_calls: int = DEFAULT_MAX_CALLS,
    pace_s: float = 0.0,
    whole: Sequence[Fact] | None = None,
) -> list[Explained]:
    """Translate the texts of a finished run's closed cases of `match` (its moments and its
    recap, as they left the Guard) into each of `langs`; every handoff goes to `log`. A case that
    is no narrative has nothing to translate and is left out. `whole`: the match's
    `match_facts`, if already computed. The cases come out in the order they end."""
    langs = tuple(dict.fromkeys(Lang(lang) for lang in langs))
    cases = [c.with_translations(langs) for c in cases if c.narrative is not None]
    if not cases:
        return []
    evidence: dict[str, Evidence] = {}
    for case in cases:  # every case is checked against the engine before any call
        if case.is_recap:
            whole = match_facts(match) if whole is None else whole
            evidence[case.moment_id] = recap_evidence(match, case, whole)
        else:
            evidence[case.moment_id] = moment_evidence(match, case)
    translator = Translator(client, match)
    budget, pace = CallBudget(max_calls, translator.max_requests), Pace(pace_s)
    start = _Start(log)
    writer = TranslatorExecutor(translator, budget, log, pace)
    guard = GuardExecutor(log, evidence)
    due = lambda case: case.pending_translation is not None  # noqa: E731
    workflow = (
        WorkflowBuilder(start_executor=start)
        .add_edge(start, writer)
        .add_edge(writer, guard)
        .add_edge(guard, writer, condition=due)
        .build()
    )
    result = await workflow.run(Closed(tuple(cases)))
    return sorted(
        result.get_outputs(), key=lambda e: (e.case.period, e.case.end_ms, e.case.moment_id)
    )

import asyncio
import json

import pytest
from real import match

from matchlens.events import EventType, display_clock
from matchlens.explain import persona
from matchlens.explain.analyst import DRAFT_SCHEMA, EFFORT, MAX_TOKENS, RULES, moment_prompt
from matchlens.explain.fake import FakeChatClient, ScriptExhausted, by_moment, echo
from matchlens.explain.guard import check, judge, moment_evidence
from matchlens.explain.persona import PersonaEditor, persona_prompt
from matchlens.explain.state import (
    PERSONA_ATTEMPTS,
    Attempt,
    CallError,
    CallFailure,
    Draft,
    MomentCase,
    Persona,
    Rendition,
)
from matchlens.facts import facts_at


def narrative_case(seed: int = 7, kind: EventType = EventType.GOAL) -> MomentCase:
    """A real moment whose Analyst draft (the `--fake` echo) passed the Guard."""
    m = match(seed)
    e = next(e for e in m.events if e.type is kind)
    case = MomentCase(
        run_id="r1",
        match_id=m.meta.match_id,
        moment_id=f"{m.meta.match_id}-k0",
        trigger_ids=(e.related, e.event_id),
        period=e.period,
        start_ms=max(0, e.clock_ms - 10_000),
        end_ms=e.clock_ms,
        display_clock=display_clock(e.period, e.clock_ms),
        facts=tuple(f.to_dict() for f in facts_at(m, e.period, e.clock_ms)),
    )
    draft = Draft.from_dict(json.loads(echo(moment_prompt(case, m))))
    case = case.with_attempt(Attempt(1, "fake", draft))
    case = case.with_verdict(judge(case, moment_evidence(m, case)))
    assert case.narrative == draft
    return case.with_personas([Persona.FAN])


def test_the_prompt_names_the_moment_the_caption_and_only_the_facts_it_may_cite():
    case = narrative_case()
    prompt = persona_prompt(case, case.renditions[0], match(7))
    lines = prompt.splitlines()
    assert lines[0] == f"Persona fan for moment m7-k0 at clock {case.display_clock}."
    text = json.dumps(case.narrative.text, ensure_ascii=False)
    assert f"The caption that passed the Guard: {text}" in lines
    assert f"Caption JSON: {json.dumps(case.narrative.to_dict(), ensure_ascii=False)}" in lines
    listed = {line.split(" | ")[0][2:] for line in lines if line.startswith("- m7/")}
    cited = {f for c in case.narrative.claims for f in c.fact_ids}
    readings = {f["fact_id"] for f in case.facts if f["name"].endswith("_reading")}
    stamp = f"{case.period}-{case.end_ms}"
    scene = {f"m7/clock/at-{stamp}/all", f"m7/minute/at-{stamp}/all", f"m7/score/to-{stamp}/all"}
    assert readings and scene and cited <= listed and readings <= listed
    assert listed == cited | readings | scene
    assert "Earlier attempts" not in prompt
    for line in ("Home: Saltreach FC. Away: Corrowmere Athletic.", "Trigger events"):
        assert any(x.startswith(line) for x in lines), line


def test_a_retry_reads_the_rejected_attempt_and_its_reasons():
    case = narrative_case()
    bad = Attempt(1, "fake", Draft("A moment to remember.", ()))
    r = case.renditions[0].with_attempt(bad)
    case = case.with_rendition(r)
    r = r.with_verdict(judge(case, moment_evidence(match(7), case)))
    prompt = persona_prompt(case.with_rendition(r), r, match(7))
    assert 'Earlier attempts, all rejected:\n- Attempt 1: "A moment to remember."' in prompt
    assert "  - no_claims: " in prompt


def test_the_prompt_refuses_a_case_without_a_narrative():
    case = narrative_case()
    with pytest.raises(ValueError, match="no narrative"):
        open_case = MomentCase.from_dict(
            case.to_dict() | {"attempts": [], "outcome": "pending", "renditions": []}
        )
        persona_prompt(open_case, case.renditions[0], match(7))


def test_the_request_carries_the_persona_s_instructions_and_the_draft_schema():
    case = narrative_case()
    r = case.renditions[0]
    client = FakeChatClient(echo)
    attempt = asyncio.run(PersonaEditor(client, match(7)).attempt(case, r))
    [(messages, options)] = client.requests
    assert options["instructions"] == persona.INSTRUCTIONS[Persona.FAN]
    assert options["instructions"].endswith(RULES)  # the Guard's rules, as the Analyst's
    assert options["response_format"] == DRAFT_SCHEMA
    assert (options["output_config"], options["max_tokens"]) == ({"effort": EFFORT}, MAX_TOKENS)
    assert [m.text for m in messages] == [persona_prompt(case, r, match(7))]
    assert (attempt.n, attempt.model, attempt.requests, attempt.draft) == (
        1,
        "fake",
        1,
        case.narrative,
    )
    assert check(attempt.draft, case, moment_evidence(match(7), case)).passed


def test_the_fan_role_states_what_a_fan_gets():
    role = persona.ROLES[Persona.FAN]
    for phrase in (
        "casual fan",
        "one or two short sentences",
        "at most 2 numbers",
        "a reading's phrase rather than a percentage",
        "A claim that uses a reading's phrase cites that reading and needs no number.",
        "Make it plainly different from the caption, never a copy",
        "drop the clock time, every percentage and every shirt number, keep the score",
        "keep only its most important sentence",
        "add nothing: no word of praise or blame of your own",
        "exactly as it checked the caption",
    ):
        assert phrase in role, phrase


def test_a_rendition_that_takes_no_further_attempt_is_refused_before_the_call():
    case = narrative_case()
    r = case.renditions[0]
    editor = PersonaEditor(FakeChatClient([]), match(7))
    waiting = r.with_attempt(Attempt(1, "fake", case.narrative))
    with pytest.raises(ValueError, match="not judged"):
        asyncio.run(editor.attempt(case.with_rendition(waiting), waiting))
    closed = Rendition(Persona.FAN).fallback()
    with pytest.raises(ValueError, match="no further attempt"):
        asyncio.run(editor.attempt(case, closed))
    failed = CallFailure(CallError.TIMEOUT, "x")
    full = Rendition(Persona.FAN)
    for n in range(1, PERSONA_ATTEMPTS + 1):
        full = full.with_attempt(Attempt(n, "fake", None, error=failed))
        full = full.with_verdict(judge(case.with_rendition(full), moment_evidence(match(7), case)))
    with pytest.raises(ValueError, match="no further attempt"):
        asyncio.run(editor.attempt(case.with_rendition(full), full))


def test_a_failed_call_is_an_attempt_with_its_reason():
    case = narrative_case()
    client = FakeChatClient(["not json"])
    attempt = asyncio.run(PersonaEditor(client, match(7)).attempt(case, case.renditions[0]))
    assert attempt.draft is None and attempt.error.code is CallError.INVALID_REPLY


def test_the_fake_scripts_a_rendition_by_moment_and_persona():
    case = narrative_case()
    prompt = persona_prompt(case, case.renditions[0], match(7))
    script = by_moment({"m7-k0": ["analyst"], "m7-k0/fan": ["fan 1"]})
    assert script(prompt) == "fan 1"
    with pytest.raises(ScriptExhausted, match="m7-k0/fan"):
        by_moment({"m7-k0": ["analyst"]})(prompt)
    assert json.loads(echo(prompt)) == case.narrative.to_dict()

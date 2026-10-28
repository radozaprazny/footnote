"""The Recap Writer: a match's recap at full time passes the Guard against the whole match's
facts, or is the deterministic recap made of them; the workflow, the log and the command."""

import asyncio
import dataclasses
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import real
from hypothesis import given, settings
from hypothesis import strategies as st
from real import cli_on_v1  # noqa: F401 (autouse: the CLI replays on v1)
from test_explain_workflow import KINDS, kind_of, reply

from matchlens import cli
from matchlens.events import EventType
from matchlens.explain import fulltime
from matchlens.explain import recap as recap_module
from matchlens.explain.detector import detect
from matchlens.explain.fake import FakeChatClient, by_moment, echo
from matchlens.explain.fulltime import fallback_recap, recap_case
from matchlens.explain.guard import (
    MAX_TEXT,
    RECAP_MAX_TEXT,
    check,
    moment_evidence,
    recap_evidence,
)
from matchlens.explain.log import Handoff, HandoffLog, Role, read_handoffs
from matchlens.explain.recap import RecapWriter, recap_prompt, write_recap
from matchlens.explain.state import (
    MAX_ATTEMPTS,
    PERSONA_ATTEMPTS,
    RECAP_ID,
    Attempt,
    Claim,
    Draft,
    MomentCase,
    MomentOutcome,
    Persona,
    Reason,
    ReasonCode,
    Verdict,
)
from matchlens.explain.summary import summarize
from matchlens.league import load_league
from matchlens.stats.readings import VOCABULARY

SEEDS = (0, 3, 7)  # 3 and 7: five goals, the most of seeds 0–49
FAN = Persona.FAN
ANSWERS = ("pass", "rejected", "invalid", "refusal")


def case_of(seed: int) -> MomentCase:
    return recap_case(real.match(seed), "r1", real.facts(seed))


def evidence_of(seed: int, case: MomentCase | None = None):
    return recap_evidence(real.match(seed), case or case_of(seed), real.facts(seed))


def _club(team: str) -> str:
    return next(c.name for c in load_league().clubs if c.id == team)


def run_recap(client, max_calls=40, personas=(), seed=7, narratives=()):
    with tempfile.TemporaryDirectory() as tmp:
        log = HandoffLog(Path(tmp) / "recap.jsonl")
        out = asyncio.run(
            write_recap(
                real.match(seed),
                client,
                log,
                run_id="r1",
                narratives=narratives,
                max_calls=max_calls,
                personas=personas,
                whole=real.facts(seed),
            )
        )
        return out, read_handoffs(log.path)


def scripted(writer: list[str], fan: list[str] = ()) -> FakeChatClient:
    script = {RECAP_ID: [reply(k) for k in writer], f"{RECAP_ID}/fan": [reply(k) for k in fan]}
    return FakeChatClient(by_moment(script))


# --- the case and its evidence ------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_a_recap_is_the_final_whistle_and_every_goal_with_the_whole_match_s_facts(seed):
    m = real.match(seed)
    case = case_of(seed)
    end = [e for e in m.events if e.type is EventType.PERIOD_END][-1]
    goals = [e.event_id for e in m.events if e.type is EventType.GOAL]
    assert case.is_recap and case.moment_id == RECAP_ID
    assert case.trigger_ids == (end.event_id, *goals)
    assert (case.period, case.start_ms, case.end_ms) == (2, 0, end.clock_ms)
    evidence = evidence_of(seed)  # it checks the case's facts against the engine
    assert {f["fact_id"] for f in case.facts} <= evidence.facts.keys()
    for f in case.facts:  # a club's or the match's, never a player's
        assert f["player"] is None
        scope = f["fact_id"].split("/")[2]
        assert scope == "match" or scope[:3] in ("at-", "to-"), f["fact_id"]
    halves = {f.fact_id for f in real.facts(seed) if f.fact_id.split("/")[2] in ("p1", "p2")}
    assert halves  # a half's facts would judge without naming the half: not a recap's
    whole = {f.fact_id for f in real.facts(seed)} - halves
    assert whole == evidence.facts.keys() & {f.fact_id for f in real.facts(seed)}
    extra = evidence.facts.keys() - whole  # each goal's minute and the score it made
    assert len(extra) == 2 * len(goals)
    for fact_id in extra:
        fact = evidence.facts[fact_id]
        assert fact.name in ("minute", "score") and fact.end in {
            (e.period, e.clock_ms) for e in m.events if e.event_id in goals
        }
    assert evidence.event_ids == {e.event_id for e in m.events}
    assert MomentCase.from_dict(json.loads(json.dumps(case.to_dict()))) == case


def test_the_recap_prompt_names_each_goal_s_facts():
    m = real.match(7)
    prompt = recap_prompt(case_of(7), m)
    assert prompt.startswith("Recap of match m7 at clock 90+3:22 (full time).\n")
    assert "Facts (fact_id | write as | what it counts | when):" in prompt
    assert "- m7/score/match/all | 3–2 | score of the match | the whole match" in prompt
    assert (
        "- m7/minute/at-1-258931/all | 5' | minute of the match | when goal "
        "m7-e00073 was scored, not at full time" in prompt
    )
    assert "- m7/goal_reading/at-1-258931/cor | take the lead |" in prompt
    assert "Key moments" not in prompt  # no narratives given
    with pytest.raises(ValueError, match="no recap"):
        recap_prompt(detect(m, "r1")[0], m)


# --- the deterministic recap --------------------------------------------------------------------


def test_the_deterministic_recap_of_match_0():
    case = case_of(0)
    draft = fallback_recap(real.match(0), case, evidence_of(0))
    assert draft.text == (
        "Vellbridge Town 1–0 Quarrendale Rovers at full time. Goals by Malik Sennabe at 5'. "
        "Possession was 52% for "
        "Vellbridge Town and 48% for Quarrendale Rovers. Pass completion was 86% for Vellbridge "
        "Town and 84% for Quarrendale Rovers. The play kept a steady tempo."
    )
    assert [c.fact_ids for c in draft.claims] == [
        ("m0/score/match/all",),
        ("m0/minute/at-1-294568/all",),
        ("m0/possession/match/vel", "m0/possession/match/qrd"),
        ("m0/pass_completion/match/vel", "m0/pass_completion/match/qrd"),
        ("m0/chaos_reading/match/all",),
    ]
    assert draft.claims[1].event_ids == case.trigger_ids[1:]
    assert all(c.event_ids == case.trigger_ids[:1] for i, c in enumerate(draft.claims) if i != 1)


def test_the_deterministic_recap_of_a_match_without_a_goal_has_no_scorers():
    m = real.match(14)  # 0–0, as seed 16
    case = case_of(14)
    assert case.trigger_ids == case.trigger_ids[:1]  # the final whistle only
    draft = fallback_recap(m, case, evidence_of(14))
    assert check(draft, case, evidence_of(14)).passed
    assert draft.text.startswith(f"{_club(m.meta.home)} 0–0 {_club(m.meta.away)} at full time.")
    assert " Possession was " in draft.text
    assert len(draft.claims) == 4 and "Goals by" not in draft.text


@pytest.mark.parametrize("seed", SEEDS)
def test_the_deterministic_recap_always_passes(seed):
    m, case, evidence = real.match(seed), case_of(seed), evidence_of(seed)
    draft = fallback_recap(m, case, evidence)
    assert check(draft, case, evidence).passed
    assert len(draft.text) <= RECAP_MAX_TEXT and len(draft.claims) == 5
    names = {p.id: p.name for c in load_league().clubs for p in c.players}
    scorers = [names[e.player] for e in m.events if e.type is EventType.GOAL]
    assert draft.claims[1].text.startswith(f"Goals by {scorers[0]} at ")
    assert draft.claims[1].text.count(" at ") == len(scorers)
    assert draft.claims[1].event_ids == case.trigger_ids[1:]


@settings(deadline=None, max_examples=40)
@given(st.sampled_from(SEEDS), st.data())
def test_the_deterministic_recap_takes_its_sentences_in_order_up_to_the_limit(seed, data):
    """Exactly on the limit a sentence fits, one character under it does not, nor any after it;
    whatever fits passes the Guard."""
    m, case, evidence = real.match(seed), case_of(seed), evidence_of(seed)
    full = fallback_recap(m, case, evidence)
    sizes = [len(" ".join(f"{c.text}." for c in full.claims[:k])) for k in range(1, 6)]
    k = data.draw(st.integers(1, 5))
    for limit, fits in ((sizes[k - 1], k), (sizes[k - 1] - 1, k - 1)):
        if fits == 0:
            continue  # the score always fits the real limit
        with mock.patch.object(fulltime, "RECAP_MAX_TEXT", limit):
            draft = fallback_recap(m, case, evidence)
        assert draft.claims == full.claims[:fits]
        assert len(draft.text) == sizes[fits - 1] <= limit
        assert check(draft, case, evidence).passed


# --- the Guard on a recap -----------------------------------------------------------------------


FINAL = "Saltreach FC 3–2 Corrowmere Athletic at full time."


def with_final(text: str, *claims: Claim) -> Draft:
    """`text` after the final score of m7, with its claim first."""
    return Draft(f"{FINAL} {text}".strip(), (score_claim(), *claims))


def score_claim() -> Claim:
    return Claim(FINAL[:-1], ("m7/score/match/all",), case_of(7).trigger_ids[:1])


def test_a_recap_has_600_characters_at_most_and_a_moment_still_1000():
    assert (RECAP_MAX_TEXT, MAX_TEXT) == (600, 1000)  # the plan's limits
    case, evidence = case_of(7), evidence_of(7)
    for size, passed in ((RECAP_MAX_TEXT, True), (RECAP_MAX_TEXT + 1, False)):
        draft = with_final("a" * (size - len(FINAL) - 1))
        verdict = check(draft, case, evidence)
        assert len(draft.text) == size and verdict.passed is passed, verdict.reasons
        assert passed or [r.code for r in verdict.reasons] == [ReasonCode.TOO_LONG]
    moment = detect(real.match(7), "r1")[0]
    m_evidence = moment_evidence(real.match(7), moment)
    score = next(f for f in moment.facts if f["name"] == "score")
    claim = Claim(f"The score is {score['display']}", (score["fact_id"],), moment.trigger_ids[:1])
    head = f"{claim.text}."
    for size, passed in ((RECAP_MAX_TEXT + 1, True), (MAX_TEXT, True), (MAX_TEXT + 1, False)):
        text = head + " " + "a" * (size - len(head) - 1)
        assert check(Draft(text, (claim,)), moment, m_evidence).passed is passed


def test_a_recap_states_the_final_score_in_a_claim_that_cites_it_and_a_moment_need_not():
    case, evidence = case_of(7), evidence_of(7)
    assert check(with_final(""), case, evidence).passed
    end, goal = case.trigger_ids[:2]
    last = Claim("it is 3–2", ("m7/score/to-2-2642399/all",), (end,))  # the last goal's score
    unwritten = Claim("Saltreach FC have the final word", ("m7/score/match/all",), (end,))
    possession = ("m7/score/match/all", "m7/possession/match/slt")
    other = Claim("Saltreach FC have 48% possession", possession, (end,))
    for draft in (
        Draft("Saltreach FC have 48% possession.", (other,)),  # cited, another number written
        Draft("Adrien Pellacourt scores at 5'.", (minute_claim(goal),)),  # no final score
        Draft("At the last goal it is 3–2.", (last,)),  # the same numbers, but not the final
        Draft("Saltreach FC have the final word.", (unwritten,)),  # cited, never written
    ):
        verdict = check(draft, case, evidence)
        assert ReasonCode.NO_FINAL_SCORE in [r.code for r in verdict.reasons], draft.text
    moment = detect(real.match(7), "r1")[0]
    m_evidence = moment_evidence(real.match(7), moment)
    score = next(f for f in moment.facts if f["name"] == "score")
    claim = Claim(f"It is {score['display']}", (score["fact_id"],), moment.trigger_ids[:1])
    assert check(Draft(f"{claim.text}.", (claim,)), moment, m_evidence).passed


def minute_claim(goal: str) -> Claim:
    return Claim("Adrien Pellacourt scores at 5'", ("m7/minute/at-1-258931/all",), (goal,))


def test_a_recap_cites_only_the_whole_match_s_facts_and_events_that_exist():
    case, evidence = case_of(7), evidence_of(7)
    end, goal = case.trigger_ids[:2]
    assert check(
        with_final("Adrien Pellacourt scores at 5'.", minute_claim(goal)), case, evidence
    ).passed
    text = "Saltreach FC are evenly matched."
    for fact_id, event_id, code in (
        ("m7/possession/to-1-600000/cor", end, ReasonCode.UNKNOWN_FACT),  # mid-match: no
        ("m7/momentum_reading/p1/slt", end, ReasonCode.UNKNOWN_FACT),  # a half's: no
        ("m7/minute/at-1-258931/all", "m7-e99999", ReasonCode.UNKNOWN_EVENT),
    ):
        draft = with_final(text, Claim(text[:-1], (fact_id,), (event_id,)))
        verdict = check(draft, case, evidence)
        assert code in [r.code for r in verdict.reasons], (fact_id, verdict.reasons)
    whole = Claim(text[:-1], ("m7/momentum_reading/match/slt",), (end,))
    assert check(with_final(text, whole), case, evidence).passed  # the match's: yes


def test_every_numeral_and_phrase_of_a_recap_must_be_a_cited_display():
    case, evidence = case_of(7), evidence_of(7)
    end = case.trigger_ids[0]
    cited = Claim("Saltreach FC are in the lead", ("m7/score_reading/match/slt",), (end,))
    assert check(with_final("Saltreach FC are in the lead.", cited), case, evidence).passed
    for text, claim, code in (
        ("It is 3–1 here.", "It is 3–1 here", ReasonCode.NUMBER_NOT_CITED),
        ("Corrowmere Athletic are in the lead.", None, ReasonCode.PHRASE_NOT_CITED),
        ("Saltreach FC are on top.", "Saltreach FC are on top", ReasonCode.PHRASE_NOT_CITED),
    ):
        ids = ("m7/score/match/all",) if claim and "3–1" in text else cited.fact_ids
        verdict = check(with_final(text, Claim(claim or text[:-1], ids, (end,))), case, evidence)
        assert code in [r.code for r in verdict.reasons], (text, verdict.reasons)
    assert "in the lead" in VOCABULARY.values()


# --- the workflow -------------------------------------------------------------------------------


def policy(writer: list[str], fan: list[str], max_calls: int):
    """The recap's attempts and its fan rendition's, written out: a pass ends either; a retry
    after any other attempt that called the model (3 attempts, a rendition 2); an attempt the
    budget refuses is skipped and ends it."""
    calls, done, fan_done = 0, [], []
    for kind in writer[:MAX_ATTEMPTS]:
        if calls >= max_calls:
            done.append("skipped")
            break
        calls += 1
        done.append(kind)
        if kind == "pass":
            break
    if done[-1] == "pass":
        for kind in fan[:PERSONA_ATTEMPTS]:
            if calls >= max_calls:
                fan_done.append("skipped")
                break
            calls += 1
            fan_done.append(kind)
            if kind == "pass":
                break
    return done, fan_done, calls


@settings(deadline=None, max_examples=30)
@given(
    st.lists(st.sampled_from(KINDS), min_size=3, max_size=3),
    st.lists(st.sampled_from(ANSWERS), min_size=2, max_size=2),
    st.integers(0, 6),
)
def test_the_recap_that_leaves_passed_the_guard_or_is_the_facts(writer, fan, max_calls):
    client = scripted(writer, fan)
    out, handoffs = run_recap(client, max_calls, personas=(FAN,))
    case = out.case
    evidence = evidence_of(7, case)
    want, want_fan, calls = policy(writer, fan, max_calls)
    assert [kind_of(a) for a in case.attempts] == want
    assert len(case.attempts) <= MAX_ATTEMPTS
    assert check(out.cue, case, evidence).passed  # whatever leaves, passed the Guard
    assert check(out.for_persona(FAN), case, evidence).passed
    if want[-1] == "pass":
        assert case.outcome is MomentOutcome.NARRATIVE and out.cue == case.narrative
        (r,) = case.renditions
        assert [kind_of(a) for a in r.attempts] == want_fan
    else:  # the deterministic recap, and no rendition of it
        assert case.outcome is MomentOutcome.STATS_ONLY and case.renditions == ()
        assert out.cue == fallback_recap(real.match(7), case, evidence)
    assert len(client.requests) == calls <= max_calls
    s = summarize(handoffs)
    assert (s.moments, s.crashed, s.total_requests) == (1, (), calls)
    assert len(handoffs) == 1 + 2 * len(case.attempts) + 2 * sum(
        len(r.attempts) for r in case.renditions
    )
    assert handoffs[0].sender is Role.DETECTOR and handoffs[0].receiver is Role.RECAP_WRITER
    assert {h.sender for h in handoffs} <= {
        Role.DETECTOR,
        Role.RECAP_WRITER,
        Role.GUARD,
        Role.PERSONA_EDITOR,
    }
    assert handoffs[-1].receiver is Role.RENDER and handoffs[-1].case == case


def test_the_recap_writer_reads_the_run_s_narratives_and_the_fake_recap_passes():
    moment = detect(real.match(7), "r1")[0]
    said = Attempt(1, "fake", Draft("Context only.", ()), verdict=Verdict(True, ()))
    narrated = dataclasses.replace(moment, attempts=(said,), outcome=MomentOutcome.NARRATIVE)
    client = FakeChatClient(by_moment({RECAP_ID: [echo]}))
    out, _ = run_recap(client, narratives=[narrated, moment])  # a case without one is left out
    prompt = "".join(msg.text or "" for msg in client.requests[0][0])
    assert "Key moments as the Analyst wrote them" in prompt
    assert f'- {moment.display_clock}: "Context only."' in prompt
    assert out.case.outcome is MomentOutcome.NARRATIVE
    assert out.cue.text == "The score is 3–2."  # the fake copies the match's score
    assert out.cue.claims[0].fact_ids == ("m7/score/match/all",)


def test_the_recap_writer_refuses_before_the_call_what_takes_no_attempt():
    """No billed call for a moment, a closed recap, a fourth attempt or an unjudged one."""
    client = FakeChatClient([])  # any call would raise ScriptExhausted
    writer = RecapWriter(client, real.match(7))
    case = case_of(7)
    refusal = Verdict(False, (Reason(ReasonCode.NO_CLAIMS, "a narrative needs claims"),))
    rejected = Attempt(1, "fake", Draft("x", ()), verdict=refusal)
    unjudged = Attempt(1, "fake", Draft("x", ()))
    tried = tuple(dataclasses.replace(rejected, n=n) for n in (1, 2, 3))
    for refused, match in (
        (detect(real.match(7), "r1")[0], "no recap"),
        (dataclasses.replace(case, outcome=MomentOutcome.STATS_ONLY), "no further attempt"),
        (dataclasses.replace(case, attempts=tried), "no further attempt"),
        (dataclasses.replace(case, attempts=(unjudged,)), "not judged"),
    ):
        with pytest.raises(ValueError, match=match):
            asyncio.run(writer.attempt(refused))
    assert client.requests == []
    two = dataclasses.replace(case, attempts=tried[:2])
    writer = RecapWriter(FakeChatClient(by_moment({RECAP_ID: [echo] * 3})), real.match(7))
    assert asyncio.run(writer.attempt(two)).n == 3  # the third attempt is still allowed


def test_only_the_recap_writer_drafts_a_recap_and_only_the_analyst_a_moment():
    recap = case_of(7)
    moment = __import__("matchlens.explain.detector").explain.detector.detect(real.match(7), "r1")[
        0
    ]
    ts = "2026-10-24T10:00:00.000+00:00"
    Handoff(ts, Role.DETECTOR, Role.RECAP_WRITER, recap)
    Handoff(ts, Role.DETECTOR, Role.ANALYST, moment)
    for sender, receiver, case in (
        (Role.DETECTOR, Role.ANALYST, recap),
        (Role.DETECTOR, Role.RECAP_WRITER, moment),
    ):
        with pytest.raises(ValueError, match="cannot go from"):
            Handoff(ts, sender, receiver, case)


# --- the command --------------------------------------------------------------------------------


@pytest.fixture
def a_run(tmp_path):
    """A `--fake` explain run of m7 up to 28:20 (three moments)."""
    assert cli.main(["explain", "m7", "--fake", "--until", "28:20", "--runs", str(tmp_path)]) == 0
    (run,) = (tmp_path / "m7").iterdir()
    return run


def test_recap_command_writes_its_log_and_summary_into_the_run(a_run, capsys):
    capsys.readouterr()
    assert cli.main(["recap", "m7", "--run", str(a_run), "--fake", "--persona", "fan"]) == 0
    out, err = capsys.readouterr()
    assert out.startswith("recap 90+3:22 narrative (1): The score is 3–2.\n  fan passed (1): ")
    assert "recap: by the Recap Writer; 1 attempts, 1 requests, 0 skipped;" in out
    assert "recap.jsonl" in err
    handoffs = read_handoffs(a_run / "recap.jsonl")
    assert {h.case.run_id for h in handoffs} == {
        read_handoffs(a_run / "handoffs.jsonl")[0].case.run_id
    }
    summary = json.loads((a_run / "recap.json").read_text())
    assert (summary["moments"], summary["narratives"], summary["total_requests"]) == (1, 1, 2)
    assert summary["settings"]["personas"] == ["fan"]
    assert cli.main(["cues", "--seed", "7", "--run", str(a_run)]) == 0
    out, err = capsys.readouterr()
    assert "m7: the recap from the run\n" in err
    recap = [c for c in json.loads(out)["cues"] if c["kind"] == "recap"]
    assert [c["lines"] for c in recap] == [["Recap", "The score is 3–2."]]
    assert recap[0]["renditions"]["fan"]["lines"][0] == "Fan recap"


def test_recap_command_refuses_a_second_recap_another_match_and_a_model_without_a_cap(
    a_run, capsys
):
    assert cli.main(["recap", "m7", "--run", str(a_run), "--fake"]) == 0
    capsys.readouterr()
    for argv, message in (
        (["recap", "m7", "--run", str(a_run), "--fake"], "has a recap already"),
        (["recap", "m8", "--run", str(a_run), "--fake"], "is no run of m8"),
        (["recap", "m7", "--run", str(a_run)], "needs --max-calls"),
        (["recap", "m7", "--run", str(a_run.parent / "none"), "--fake"], "cannot read the run"),
    ):
        with pytest.raises(SystemExit) as exit_:
            cli.main(argv)
        assert exit_.value.code == 2
        assert message in capsys.readouterr().err


def test_recap_command_passes_the_run_s_narratives_and_settings_and_stops_on_a_fatal_call(
    a_run, capsys, monkeypatch
):
    from matchlens.explain.analyst import FatalCallError

    seen = {}
    real_write = recap_module.write_recap

    async def spy(match, client, log, **kwargs):
        seen.update(kwargs)
        return await real_write(match, client, log, **kwargs)

    monkeypatch.setattr(recap_module, "write_recap", spy)
    argv = ["recap", "m7", "--run", str(a_run), "--fake", "--pace", "3", "--max-calls", "7"]
    assert cli.main(argv) == 0
    logged = read_handoffs(a_run / "handoffs.jsonl")
    assert [n.moment_id for n in seen["narratives"]] == [
        h.case.moment_id for h in logged if h.receiver is Role.RENDER
    ]
    assert (seen["pace_s"], seen["max_calls"], seen["personas"]) == (3, 7, ())
    assert seen["run_id"] == logged[0].case.run_id
    (a_run / "recap.jsonl").unlink()

    async def fatal(*args, **kwargs):
        raise FatalCallError("401: the token expired")

    monkeypatch.setattr(recap_module, "write_recap", fatal)
    capsys.readouterr()
    assert cli.main(["recap", "m7", "--run", str(a_run), "--fake"]) == 1
    out, err = capsys.readouterr()
    assert "matchlens recap: stopped: 401: the token expired" in err
    assert out.startswith("recap: none (the run stopped)")


def test_cues_command_says_when_the_run_s_recap_is_refused_at_replay(a_run, capsys):
    assert cli.main(["recap", "m7", "--run", str(a_run), "--fake"]) == 0
    lines = (a_run / "recap.jsonl").read_text(encoding="utf-8").splitlines()
    lines = [line.replace("The score is 3\\u20132.", "The score is 9\\u20139.") for line in lines]
    (a_run / "recap.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["cues", "--seed", "7", "--run", str(a_run)]) == 0
    out, err = capsys.readouterr()
    assert "m7: the recap from the run, refused at replay\n" in err
    (recap,) = [c for c in json.loads(out)["cues"] if c["kind"] == "recap"]
    assert recap["lines"][0] == "Full time in facts"


def test_a_recap_stopped_after_its_first_line_is_set_aside_so_a_new_try_may_run(
    a_run, capsys, monkeypatch
):
    import anthropic
    import httpx2
    from test_explain_workflow import REQUEST, caused

    denied = httpx2.Response(401, request=REQUEST)
    fatal = caused(anthropic.AuthenticationError("expired", response=denied, body=None), "401")
    monkeypatch.setattr("matchlens.explain.fake.echo", lambda prompt: (_ for _ in ()).throw(fatal))
    capsys.readouterr()
    for tries in (1, 2):  # each stopped log is kept under its own name
        assert cli.main(["recap", "m7", "--run", str(a_run), "--fake"]) == 1
        err = capsys.readouterr().err
        kept = sorted(a_run.glob("recap.stopped.*.jsonl"))
        assert len(kept) == tries and "matchlens recap: stopped: AuthenticationError" in err
        assert f"log and summary: {kept[-1]}, recap.json" in err  # the file that exists
        assert not (a_run / "recap.jsonl").exists()
        stopped = read_handoffs(kept[-1])
        assert [(h.sender, h.receiver) for h in stopped] == [(Role.DETECTOR, Role.RECAP_WRITER)]
    monkeypatch.undo()
    assert cli.main(["recap", "m7", "--run", str(a_run), "--fake"]) == 0  # a new try
    capsys.readouterr()
    assert cli.main(["cues", "--seed", "7", "--run", str(a_run)]) == 0  # the set-aside log
    assert "never left the Guard" not in capsys.readouterr().err  # is not read


def test_recap_command_refuses_a_run_without_handoffs(tmp_path, capsys):
    (tmp_path / "handoffs.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(SystemExit) as exit_:
        cli.main(["recap", "m7", "--run", str(tmp_path), "--fake"])
    assert exit_.value.code == 2 and "has no handoffs" in capsys.readouterr().err


def test_cues_command_says_when_a_recap_never_closed_or_its_fan_recap_is_refused(a_run, capsys):
    assert cli.main(["recap", "m7", "--run", str(a_run), "--fake", "--persona", "fan"]) == 0
    log = a_run / "recap.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    fan = [line for line in lines if '"to": "render"' in line]
    head, _, tail = fan[0].rpartition('"text": "The score is 3\\u20132."')  # the rendition's
    forged = f'{head}"text": "It is 9\\u20139."{tail}'
    log.write_text("\n".join([*lines[:-1], forged]) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["cues", "--seed", "7", "--run", str(a_run)]) == 0
    err = capsys.readouterr().err
    assert "m7: the recap from the run\nm7: the fan recap from the run, refused at replay\n" in err
    log.write_text("\n".join(lines[:1]) + "\n", encoding="utf-8")  # opened, never closed
    assert cli.main(["cues", "--seed", "7", "--run", str(a_run)]) == 0
    assert "m7: the run's recap never left the Guard\n" in capsys.readouterr().err


def test_the_analyst_refuses_a_recap_before_the_call():
    from matchlens.explain.analyst import Analyst

    client = FakeChatClient([])
    with pytest.raises(ValueError, match="Recap Writer's to draft"):
        asyncio.run(Analyst(client, real.match(7)).attempt(case_of(7)))
    assert client.requests == []


def test_the_persona_editor_reads_a_recap_s_final_score_and_its_goals_as_instants():
    from matchlens.explain.persona import persona_prompt
    from matchlens.explain.state import Rendition

    case = case_of(7)
    last = Claim("it is 3–2", ("m7/score/to-2-2642399/all",), case.trigger_ids[:1])
    draft = Draft("At the last goal it is 3–2.", (last,))  # cites no final score
    said = Attempt(1, "fake", draft, verdict=Verdict(True, ()))
    narrated = dataclasses.replace(case, attempts=(said,), outcome=MomentOutcome.NARRATIVE)
    prompt = persona_prompt(narrated, Rendition(FAN), real.match(7))
    assert "keep its final score (the fact m7/score/match/all) and cite it" in prompt
    assert "- m7/score/match/all | 3–2 | score of the match | the whole match" in prompt
    assert (
        "- m7/score/to-2-2642399/all | 3–2 | score of the match | when goal m7-e01606 was "
        "scored, not at full time" in prompt
    )
    assert "so far in the match" not in prompt and "at this moment" not in prompt
    assert "Persona fan for moment recap at clock 90+3:22." in prompt


def test_recap_evidence_refuses_the_facts_of_another_match():
    with pytest.raises(ValueError, match="facts of another match than m7"):
        recap_evidence(real.match(7), case_of(7), real.facts(3))


def test_the_page_s_commands_load_no_agent_framework():
    """`cues`, `serve` and the app replay a run's recap without the agents' slow imports."""
    import subprocess
    import sys

    code = (
        "import sys, matchlens.cli, matchlens.api, matchlens.render.moments, "
        "matchlens.render.recap, matchlens.explain.fulltime; "
        "print(sorted(m for m in ('agent_framework', 'anthropic', 'azure.identity') "
        "if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_a_whole_match_reading_and_a_goal_s_instant_never_share_a_claim():
    """Corrowmere took the lead at 5' and were chasing the game only at full time."""
    case, evidence = case_of(7), evidence_of(7)
    end, goal = case.trigger_ids[:2]
    minute, chasing = "m7/minute/at-1-258931/all", "m7/score_reading/match/cor"
    took, final = "m7/goal_reading/at-1-258931/cor", "m7/score/match/all"
    mixed = "Adrien Pellacourt scores at 5' and Corrowmere Athletic are chasing the game"
    split = ("Adrien Pellacourt scores at 5'", "Corrowmere Athletic are chasing the game")
    after = "It is 0–1 and Corrowmere Athletic are chasing the game"  # the score the goal made
    for text, ids in (
        (mixed, (minute, chasing)),
        (after, ("m7/score/to-1-258931/all", chasing)),
        (FINAL[:-1] + " and Corrowmere Athletic take the lead", (final, took)),
    ):
        verdict = check(with_final(f"{text}.", Claim(text, ids, (end, goal))), case, evidence)
        assert ReasonCode.PHRASE_NOT_CITED in [r.code for r in verdict.reasons], text
        assert "another time" in next(r.detail for r in verdict.reasons if r.token), verdict
    two = with_final(
        f"{split[0]}. {split[1]}.",
        Claim(split[0], (minute,), (goal,)),
        Claim(split[1], (chasing,), (end,)),
    )
    assert check(two, case, evidence).passed
    same = "Adrien Pellacourt scores at 5' and Corrowmere Athletic take the lead"
    assert check(
        with_final(f"{same}.", Claim(same, (minute, took), (goal,))), case, evidence
    ).passed


def test_a_goal_s_reading_stands_only_beside_that_goal_s_minute_and_score():
    """Corrowmere took the lead at 5' (0–1), not at 13', 90' or 3–2."""
    case, evidence = case_of(7), evidence_of(7)
    goal = case.trigger_ids[1]
    took = evidence.facts["m7/goal_reading/at-1-258931/cor"]
    lead = "Corrowmere Athletic take the lead"

    def verdict(says: str, *ids: str, facts=evidence.facts):
        text = f"Adrien Pellacourt {says} and {lead}"
        claim = Claim(text, (*ids, took.fact_id), (goal,))
        return check(
            with_final(f"{text}.", claim), case, dataclasses.replace(evidence, facts=facts)
        )

    same = ("m7/minute/at-1-258931/all", "m7/score/to-1-258931/all")
    assert verdict("scores at 5'", same[0]).passed
    assert verdict("makes it 0–1", same[1]).passed
    assert verdict("scores at 5' to make it 0–1", *same).passed
    for says, other in (
        ("scores at 13'", "m7/minute/at-1-754425/all"),  # the next goal
        ("scores at 90'", "m7/minute/at-2-2642399/all"),
        ("makes it 3–2", "m7/score/to-2-2642399/all"),
        ("scores at 5' to make it 3–2", "m7/score/to-2-2642399/all"),
    ):
        ids = (same[0], other) if "5'" in says else (other,)
        reasons = verdict(says, *ids).reasons
        assert ReasonCode.PHRASE_NOT_CITED in [r.code for r in reasons], says
        assert "that same goal" in next(r.detail for r in reasons if r.token == "take the lead")
    # another goal's reading in the claim: each phrase is of another instant than the other's
    equal = "m7/goal_reading/at-1-754425/slt"
    both = f"{lead} and Saltreach FC equalise"
    claim = Claim(both, (took.fact_id, equal), (goal,))
    tokens = {r.token for r in check(with_final(f"{both}.", claim), case, evidence).reasons}
    assert {"take the lead", "equalise"} <= tokens
    # the instant is compared exactly: a minute 1 ms before or after the goal is another's
    minute = evidence.facts[same[0]]
    for ms, passed in ((258930, False), (258931, True), (258932, False)):
        moved = dataclasses.replace(
            minute, fact_id=f"m7/minute/at-1-{ms}/all", start=(1, ms), end=(1, ms)
        )
        facts = {**evidence.facts, moved.fact_id: moved}
        assert verdict("scores at 5'", moved.fact_id, facts=facts).passed is passed, ms


def test_a_half_is_no_window_of_a_whole_match_reading():
    case, evidence = case_of(7), evidence_of(7)
    end = case.trigger_ids[0]
    reading = "m7/score_reading/match/slt"
    for when, passed in (("", True), (" in the second half", False), (" after the break", False)):
        text = f"Saltreach FC are in the lead{when}"
        verdict = check(with_final(f"{text}.", Claim(text, (reading,), (end,))), case, evidence)
        assert verdict.passed is passed, (when, verdict.reasons)


def test_the_final_score_is_cited_and_written_in_the_same_claim():
    case, evidence = case_of(7), evidence_of(7)
    end = case.trigger_ids[0]
    cites = Claim("Saltreach FC have the final word", ("m7/score/match/all",), (end,))
    writes = Claim("it is 3–2", ("m7/score/to-2-2642399/all",), (end,))
    draft = Draft("Saltreach FC have the final word. At the end it is 3–2.", (cites, writes))
    verdict = check(draft, case, evidence)
    assert ReasonCode.NO_FINAL_SCORE in [r.code for r in verdict.reasons]


def test_a_recap_that_breaks_is_set_aside_and_raised(a_run, monkeypatch):
    async def broken(self, case):
        raise RuntimeError("a bug")

    monkeypatch.setattr(RecapWriter, "attempt", broken)
    with pytest.raises(Exception, match="a bug"):
        cli.main(["recap", "m7", "--run", str(a_run), "--fake"])
    assert not (a_run / "recap.jsonl").exists()
    (kept,) = a_run.glob("recap.stopped.*.jsonl")
    assert [(h.sender, h.receiver) for h in read_handoffs(kept)] == [
        (Role.DETECTOR, Role.RECAP_WRITER)
    ]

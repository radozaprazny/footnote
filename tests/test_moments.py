"""Moment cues: a key moment's text on the overlay is what the Explain workflow let out, replayed
from a run's handoff log, and a rejected text never shows."""

import dataclasses
import json
from unittest import mock

import pytest
import real
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from test_explain_workflow import KINDS, memo_facts_at, moments, reply, run_workflow, scripted

from matchlens import cli
from matchlens.api import LiveLimits, create_app
from matchlens.explain import detector, guard
from matchlens.explain.detector import detect
from matchlens.explain.fake import FakeChatClient, by_moment, echo
from matchlens.explain.guard import moment_evidence, stats_only_draft
from matchlens.explain.log import Handoff, HandoffLog, Role
from matchlens.explain.state import (
    Draft,
    MomentOutcome,
    Persona,
    Reason,
    ReasonCode,
    RenditionOutcome,
    Verdict,
)
from matchlens.render.cues import CueKind, cue_timeline, ordered
from matchlens.render.moments import FAN_VIEW, NARRATIVE, STATS_ONLY, match_cues, moment_cues
from matchlens.render.recap import match_recap

FAN = Persona.FAN


def cues_of(handoffs=(), m=None):
    """`moment_cues` of m7 (or `m`), each instant's facts computed once per test run."""
    with (
        mock.patch.object(detector, "facts_at", memo_facts_at),
        mock.patch.object(guard, "facts_at", memo_facts_at),
    ):
        return moment_cues(m or real.match(7), handoffs)


def recap_of(seed: int):
    """The recap cue without a run: the deterministic recap."""
    return match_recap(real.match(seed), (), real.facts(seed)).cue()


def moment_of(cue) -> str:
    return cue.cue_id.rsplit("/", 1)[1]


def run(kinds: dict[str, list[str]]):
    """The workflow over m7 up to 28:20 (three moments) with a scripted Analyst."""
    return run_workflow(scripted(kinds))


def fan_pass(prompt: str) -> str:
    """A Persona Editor's draft that passes and differs from the caption: the fake's score
    claim, reworded."""
    draft = json.loads(echo(prompt))
    text = draft["text"].replace("The score is ", "Now ")
    claims = [c | {"text": c["text"].replace("The score is ", "Now ")} for c in draft["claims"]]
    return json.dumps({"text": text, "claims": claims})


def run_with_fan(analyst: dict[str, list[str]], fan: dict[str, list[str]]):
    """`run` with the fan persona; a fan `pass` is `fan_pass`."""
    script = {m: [reply(k) for k in ks] for m, ks in analyst.items()}
    script |= {
        f"{m}/fan": [fan_pass if k == "pass" else reply(k) for k in ks] for m, ks in fan.items()
    }
    return run_workflow(FakeChatClient(by_moment(script)), personas=(FAN,))


def rejected_texts(handoffs) -> set[str]:
    attempts = [a for h in handoffs for a in h.case.attempts]
    attempts += [a for h in handoffs for r in h.case.renditions for a in r.attempts]
    return {
        a.draft.text
        for a in attempts
        if a.draft is not None and a.verdict is not None and not a.verdict.passed
    }


# --- the property -------------------------------------------------------------------------------


def cited(draft: Draft) -> tuple[str, ...]:
    return tuple(dict.fromkeys(f for c in draft.claims for f in c.fact_ids))


@settings(deadline=None)  # an event loop and a workflow per example
@given(
    st.lists(st.lists(st.sampled_from(KINDS), min_size=3, max_size=3), min_size=3, max_size=3),
    st.lists(st.lists(st.sampled_from(KINDS), min_size=2, max_size=2), min_size=3, max_size=3),
)
def test_a_moment_cue_shows_what_the_workflow_let_out_and_never_a_rejected_text(scripts, fan):
    """For the analyst and the fan: a fan reads the Persona Editor's draft that passed, else
    what the analyst reads."""
    ids = [c.moment_id for c in moments()]
    explained, handoffs = run_with_fan(
        dict(zip(ids, scripts, strict=True)), dict(zip(ids, fan, strict=True))
    )
    cues = {moment_of(c): c for c in cues_of(handoffs)}
    for e in explained:
        cue = cues[e.case.moment_id]
        assert cue.lines[1] == e.cue.text  # the passed draft or the stats-only text, exactly
        label = NARRATIVE if e.case.narrative is not None else STATS_ONLY
        assert cue.lines[0].startswith(f"{label} · ")
        assert cue.fact_ids == cited(e.cue)
        shown = e.for_persona(FAN)
        own = [r for r in e.case.renditions if r.outcome is RenditionOutcome.PASSED]
        fan_label = FAN_VIEW if own else label
        assert cue.rendition("fan").lines == (
            f"{fan_label}{cue.lines[0][len(label) :]}",
            shown.text,
        )
        assert cue.rendition("fan").fact_ids == cited(shown)
        assert cue.rendition("fan").event_ids == cue.event_ids == e.case.trigger_ids
        assert (shown.text != e.cue.text) == bool(own)  # `fan_pass` rewords
    shown = {line for c in cues.values() for r in (c, c.rendition("fan")) for line in r.lines}
    assert not rejected_texts(handoffs) & shown
    later = [c for m, c in cues.items() if m not in ids]  # the run ended at 28:20
    assert later and all(c.lines[0].startswith(f"{STATS_ONLY} · ") for c in later)
    assert all(c.rendition("fan").lines == c.lines for c in later)


# --- examples -----------------------------------------------------------------------------------


def test_rejected_drafts_stay_out_and_a_retry_that_passes_shows():
    first, second, third = (c.moment_id for c in moments())
    explained, handoffs = run(
        {
            first: ["rejected", "rejected", "rejected"],
            second: ["rejected", "pass"],
            third: ["pass"],
        }
    )
    assert rejected_texts(handoffs) == {"A moment to remember."}
    cues = {moment_of(c): c for c in cues_of(handoffs)}
    out = {e.case.moment_id: e.cue.text for e in explained}
    assert cues[first].lines[0] == "Key moment · COR"
    assert cues[first].lines[1] == out[first] != "A moment to remember."
    assert cues[second].lines == ("Analyst · SLT", out[second])
    assert cues[third].lines == ("Analyst · COR", out[third])
    assert out[second].startswith("The score is ")  # the fake Analyst's narrative


def test_a_logged_narrative_the_guard_refuses_now_shows_as_stats_only():
    (first, *_) = (c.moment_id for c in moments())
    _, handoffs = run({m.moment_id: ["pass"] for m in moments()})
    closed = next(h for h in handoffs if h.receiver is Role.RENDER and h.case.moment_id == first)
    case = closed.case
    last = case.attempts[-1]
    forged = dataclasses.replace(last, draft=Draft("The score is 9–9.", last.draft.claims))
    case = dataclasses.replace(case, attempts=(*case.attempts[:-1], forged))
    assert case.narrative.text == "The score is 9–9."  # the log says it passed
    tampered = [Handoff(h.ts, h.sender, h.receiver, case) if h is closed else h for h in handoffs]
    cue = next(c for c in cues_of(tampered) if moment_of(c) == first)
    m = real.match(7)
    expected = stats_only_draft(case, moment_evidence(m, case)).text
    assert cue.lines == ("Key moment · COR", expected)


def test_without_a_run_every_moment_is_stats_only_and_due_when_it_ends():
    m = real.match(7)
    found = detect(m, "any")
    cues = cues_of()
    assert [moment_of(c) for c in cues] == [c.moment_id for c in found]
    events = {e.event_id: e for e in m.events}
    for cue, case in zip(cues, found, strict=True):
        shot = events[case.trigger_ids[0]]
        assert cue.kind is CueKind.MOMENT and cue.ttl_ms == 8_000
        assert cue.due == (case.period, case.end_ms)
        assert cue.event_ids == case.trigger_ids
        assert (cue.team, cue.anchor) == (shot.team, (shot.start.x, shot.start.y))
        draft = stats_only_draft(case, moment_evidence(m, case))
        assert cue.lines[1] == draft.text
        assert cue.lines[0].startswith("Key moment · ")
        assert cue.fact_ids == tuple(dict.fromkeys(f for c in draft.claims for f in c.fact_ids))
    assert len(cues) == 15  # m7: 5 goals, 10 saves and woodwork
    assert cues[0].lines == (  # the clubs by their short names
        "Key moment · COR",
        "minute 5' · score 0–1 · possession COR 66% · possession SLT 34%",
    )


def test_the_page_order_puts_a_moment_after_the_goal_or_chance_it_explains():
    whole = real.timeline(7)
    assert whole == ordered([*real.cues(7), *cues_of(), recap_of(7)])
    assert whole == match_cues(real.match(7), (), real.facts(7))
    for cue in (c for c in whole if c.kind is CueKind.MOMENT):
        same = [c.kind for c in whole if c.due == cue.due]
        assert same[-1] is CueKind.MOMENT and same[0] in (CueKind.GOAL, CueKind.CHANCE), same


def test_a_draft_the_log_says_was_rejected_never_shows_even_if_it_would_pass():
    (first, *_) = (c.moment_id for c in moments())
    _, handoffs = run({m.moment_id: ["pass"] for m in moments()})
    closed = next(h for h in handoffs if h.receiver is Role.RENDER and h.case.moment_id == first)
    case = closed.case
    passing = case.attempts[-1].draft.text
    refused = Verdict(False, (Reason(ReasonCode.TOO_LONG, "logged as refused"),))
    last = dataclasses.replace(case.attempts[-1], verdict=refused)
    case = dataclasses.replace(
        case, attempts=(*case.attempts[:-1], last), outcome=MomentOutcome.STATS_ONLY
    )
    logged = [Handoff(h.ts, h.sender, h.receiver, case) if h is closed else h for h in handoffs]
    cue = next(c for c in cues_of(logged) if moment_of(c) == first)
    assert cue.lines[0] == "Key moment · COR"
    assert passing not in cue.lines


def test_a_fan_reads_the_persona_editor_s_draft_with_its_own_facts():
    explained, handoffs = run_with_fan(
        {m.moment_id: ["pass"] for m in moments()}, {m.moment_id: ["pass"] for m in moments()}
    )
    cues = {moment_of(c): c for c in cues_of(handoffs)}
    first = explained[0]
    cue = cues[first.case.moment_id]
    assert cue.lines == ("Analyst · COR", "The score is 0–1.")
    assert cue.rendition("fan").lines == ("Fan view · COR", "Now 0–1.")
    assert cue.rendition("fan").fact_ids == cited(first.case.renditions[0].draft)
    assert [c.rendition("fan").lines[0] for c in cues.values()][:4] == [
        "Fan view · COR",
        "Fan view · SLT",
        "Fan view · COR",
        "Key moment · COR",  # after 28:20: no run, no rendition
    ]


def test_a_fan_draft_the_guard_refuses_now_falls_back_to_the_analyst_s_lines():
    _, handoffs = run_with_fan(
        {m.moment_id: ["pass"] for m in moments()}, {m.moment_id: ["pass"] for m in moments()}
    )
    tampered = [forge_fan(h, "Now 9–9.") for h in handoffs]
    cues = {moment_of(c): c for c in cues_of(tampered)}
    shown = [c for c in cues.values() if c.lines[0].startswith(f"{NARRATIVE} · ")]
    assert len(shown) == 3
    for cue in shown:
        assert cue.rendition("fan").lines == cue.lines and cue.rendition("fan").fact_ids == (
            cue.fact_ids
        )
    assert not any("9–9" in line for c in cues.values() for line in c.rendition("fan").lines)


def test_a_fan_reads_no_rendition_of_a_narrative_the_guard_refuses_now():
    """A rendition exists only of a narrative: one refused at replay takes its fan draft along,
    though that draft would pass on its own."""
    (first, *_) = (c.moment_id for c in moments())
    _, handoffs = run_with_fan(
        {m.moment_id: ["pass"] for m in moments()}, {m.moment_id: ["pass"] for m in moments()}
    )
    closed = next(h for h in handoffs if h.receiver is Role.RENDER and h.case.moment_id == first)
    case = closed.case
    last = case.attempts[-1]
    forged = dataclasses.replace(last, draft=Draft("The score is 9–9.", last.draft.claims))
    case = dataclasses.replace(case, attempts=(*case.attempts[:-1], forged))
    assert case.renditions[0].draft.text == "Now 0–1."  # it passes the Guard as it is
    tampered = [Handoff(h.ts, h.sender, h.receiver, case) if h is closed else h for h in handoffs]
    cue = next(c for c in cues_of(tampered) if moment_of(c) == first)
    assert cue.lines[0] == "Key moment · COR"
    assert cue.rendition("fan").lines == cue.lines
    assert cue.rendition("fan").fact_ids == cue.fact_ids


def test_a_fan_draft_the_log_says_was_rejected_never_shows_even_if_it_would_pass():
    (first, *_) = (c.moment_id for c in moments())
    _, handoffs = run_with_fan(
        {m.moment_id: ["pass"] for m in moments()}, {m.moment_id: ["pass"] for m in moments()}
    )
    closed = next(h for h in handoffs if h.receiver is Role.RENDER and h.case.moment_id == first)
    r = closed.case.renditions[0]
    refused = Verdict(False, (Reason(ReasonCode.TOO_LONG, "logged as refused"),))
    last = dataclasses.replace(r.attempts[-1], verdict=refused)
    logged = dataclasses.replace(r, attempts=(*r.attempts[:-1], last), outcome="fallback")
    case = closed.case.with_rendition(logged)
    tampered = [Handoff(h.ts, h.sender, h.receiver, case) if h is closed else h for h in handoffs]
    cue = next(c for c in cues_of(tampered) if moment_of(c) == first)
    assert cue.lines[0] == "Analyst · COR"
    assert cue.rendition("fan").lines == cue.lines
    assert "Now 0–1." not in cue.rendition("fan").lines


def forge_fan(h: Handoff, text: str) -> Handoff:
    """`h` with its fan rendition's passed draft saying `text`, if it has one."""
    case = h.case
    if not case.renditions or case.renditions[0].draft is None:
        return h
    r = case.renditions[0]
    last = dataclasses.replace(r.attempts[-1], draft=Draft(text, r.attempts[-1].draft.claims))
    forged = dataclasses.replace(r, attempts=(*r.attempts[:-1], last))
    return Handoff(h.ts, h.sender, h.receiver, case.with_rendition(forged))


def test_a_log_of_another_match_or_moment_is_refused():
    _, handoffs = run({m.moment_id: ["pass"] for m in moments()})
    with pytest.raises(ValueError, match="a handoff of m7 in the log of m8"):
        moment_cues(real.match(8), handoffs)
    closed = next(h for h in handoffs if h.receiver is Role.RENDER)
    moved = dataclasses.replace(closed.case, trigger_ids=("m7-e00001",))
    with pytest.raises(ValueError, match="is not one of m7"):
        cues_of([Handoff(closed.ts, closed.sender, closed.receiver, moved)])


def test_the_app_refuses_handoffs_of_a_match_it_does_not_serve():
    with pytest.raises(ValueError, match="handoffs of matches not served: m9"):
        create_app([real.match(7)], handoffs={"m9": []})
    with pytest.raises(ValueError, match="two of cues, handoffs and overlays given for m7"):
        create_app([real.match(7)], cues={"m7": []}, handoffs={"m7": []})


def test_the_app_streams_a_run_s_narrative(tmp_path):
    _, handoffs = run({m.moment_id: ["pass"] for m in moments()})
    m = real.match(7)
    timeline = ordered([*cue_timeline(m, real.facts(7)), *cues_of(handoffs), recap_of(7)])
    narratives = [c for c in timeline if c.lines[0].startswith(f"{NARRATIVE} · ")]
    assert len(narratives) == 3
    with TestClient(create_app([m], handoffs={"m7": handoffs})) as client:
        body = client.get("/matches/m7/live?speed=0&hz=1").text
    sent = [json.loads(line[6:])["cue"] for line in body.splitlines() if '"cue":' in line]
    assert sent == [c.to_dict() for c in timeline]


# --- command line -------------------------------------------------------------------------------


def write_run(tmp_path, handoffs):
    log = HandoffLog(tmp_path / "run" / "handoffs.jsonl")
    log.path.parent.mkdir()
    for h in handoffs:
        log.record(h.sender, h.receiver, h.case)
    return log.path.parent


def test_cues_command_replays_a_run(capsys, tmp_path):
    _, handoffs = run({m.moment_id: ["pass"] for m in moments()})
    assert cli.main(["cues", "--seed", "7", "--run", str(write_run(tmp_path, handoffs))]) == 0
    out, err = capsys.readouterr()
    shown = json.loads(out)["cues"]
    assert sum(c["lines"][0].startswith(f"{NARRATIVE} · ") for c in shown) == 3
    assert err == (
        "m7: 3 narratives from the run, 0 refused at replay\n"
        "m7: 51 cues (chance 10, goal 5, moment 15, period_end 2, recap 1, window 18)\n"
    )


def forged_runs(tmp_path):
    """Two runs of m7 that do not fit it: a moment with other triggers, and a narrative case
    whose fact differs from the engine's."""
    _, handoffs = run({m.moment_id: ["pass"] for m in moments()})
    closed = next(h for h in handoffs if h.receiver is Role.RENDER)
    moved = dataclasses.replace(closed.case, trigger_ids=("m7-e00001",))
    fact, *rest = closed.case.facts
    changed = dataclasses.replace(closed.case, facts=({**fact, "display": "99"}, *rest))
    runs = []
    for n, case in enumerate((moved, changed)):
        log = HandoffLog(tmp_path / f"run{n}" / "handoffs.jsonl")
        log.path.parent.mkdir()
        log.record(Role.GUARD, Role.RENDER, case)
        runs.append(str(log.path.parent))
    return runs


def test_cues_command_counts_the_fan_renditions_shown_and_refused_at_replay(capsys, tmp_path):
    first = moments()[0].moment_id
    _, handoffs = run_with_fan(
        {m.moment_id: ["pass"] for m in moments()}, {m.moment_id: ["pass"] for m in moments()}
    )
    tampered = [forge_fan(h, "Now 9–9.") if h.case.moment_id == first else h for h in handoffs]
    assert cli.main(["cues", "--seed", "7", "--run", str(write_run(tmp_path, tampered))]) == 0
    out, err = capsys.readouterr()
    assert err.startswith(
        "m7: 3 narratives from the run, 0 refused at replay\n"
        "m7: 2 fan renditions from the run, 1 refused at replay\n"
    ), err
    fan = [
        c["renditions"]["fan"]["lines"][0] for c in json.loads(out)["cues"] if c["kind"] == "moment"
    ]
    assert fan[:3] == ["Analyst · COR", "Fan view · SLT", "Fan view · COR"]


def test_cues_command_counts_the_narratives_the_guard_refuses_at_replay(capsys, tmp_path):
    first = moments()[0].moment_id
    _, handoffs = run({m.moment_id: ["pass"] for m in moments()})
    closed = next(h for h in handoffs if h.receiver is Role.RENDER and h.case.moment_id == first)
    last = closed.case.attempts[-1]
    forged = dataclasses.replace(last, draft=Draft("The score is 9–9.", last.draft.claims))
    case = dataclasses.replace(closed.case, attempts=(*closed.case.attempts[:-1], forged))
    tampered = [Handoff(h.ts, h.sender, h.receiver, case) if h is closed else h for h in handoffs]
    assert cli.main(["cues", "--seed", "7", "--run", str(write_run(tmp_path, tampered))]) == 0
    err = capsys.readouterr().err
    assert err.startswith("m7: 2 narratives from the run, 1 refused at replay\n"), err


def test_a_moment_closed_twice_in_a_log_is_refused():
    _, handoffs = run({m.moment_id: ["pass"] for m in moments()})
    closed = next(h for h in handoffs if h.receiver is Role.RENDER)
    with pytest.raises(ValueError, match="is closed twice in the log"):
        cues_of([*handoffs, closed])


@pytest.mark.parametrize("command", ["cues", "serve"])
def test_a_run_that_does_not_fit_the_match_is_a_usage_error(command, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: pytest.fail("served a run that misfits"))
    for forged in forged_runs(tmp_path):
        with pytest.raises(SystemExit) as stop:
            cli.main([command, "--seed", "7", "--run", forged])
        assert stop.value.code == 2
        assert "the run of m7 does not fit the match" in capsys.readouterr().err


def test_cues_command_refuses_a_run_of_another_match(capsys, tmp_path):
    _, handoffs = run({m.moment_id: ["pass"] for m in moments()})
    with pytest.raises(SystemExit) as stop:
        cli.main(["cues", "--seed", "8", "--run", str(write_run(tmp_path, handoffs))])
    assert stop.value.code == 2
    assert "the run is of m7, not m8" in capsys.readouterr().err


def test_two_runs_of_one_match_or_a_bad_log_are_usage_errors(capsys, tmp_path):
    _, handoffs = run({m.moment_id: ["pass"] for m in moments()})
    one = write_run(tmp_path, handoffs)
    other = tmp_path / "other"
    other.mkdir()
    (other / "handoffs.jsonl").write_text((one / "handoffs.jsonl").read_text())
    with pytest.raises(SystemExit) as stop:
        cli.main(["serve", "--seed", "7", "--run", str(one), "--run", str(other)])
    assert stop.value.code == 2
    assert "two runs of m7" in capsys.readouterr().err
    (other / "handoffs.jsonl").write_text('{"v": 2}\n')
    with pytest.raises(SystemExit) as stop:
        cli.main(["cues", "--seed", "7", "--run", str(other)])
    assert stop.value.code == 2
    assert f"the run {other} has a bad handoff log" in capsys.readouterr().err


def test_a_missing_run_is_a_usage_error(capsys, tmp_path):
    with pytest.raises(SystemExit) as stop:
        cli.main(["cues", "--seed", "7", "--run", str(tmp_path / "nothing")])
    assert stop.value.code == 2
    assert "cannot read the run" in capsys.readouterr().err


def test_serve_passes_each_run_to_its_match(monkeypatch, tmp_path):
    _, handoffs = run({m.moment_id: ["pass"] for m in moments()})
    given_to = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: None)
    monkeypatch.setattr("matchlens.cli.generate_match", real.match)

    def create_app(matches, overlays, limits):
        assert limits == LiveLimits()  # the public app's (issue #2)
        given_to.update(overlays)

    monkeypatch.setattr("matchlens.api.create_app", create_app)
    run_dir = str(write_run(tmp_path, handoffs))
    assert cli.main(["serve", "--seed", "7", "--seed", "8", "--run", run_dir]) == 0
    assert list(given_to) == ["m7"]  # the run's replay, computed once before the server starts
    assert given_to["m7"].cues == match_cues(real.match(7), handoffs, real.facts(7))
    with pytest.raises(SystemExit) as stop:
        cli.main(["serve", "--seed", "8", "--run", run_dir])
    assert stop.value.code == 2

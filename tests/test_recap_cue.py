"""The recap at full time on the overlay and at `/matches/{id}/recap`: what the run's Recap Writer
wrote if the Guard passes it again, else the deterministic recap; a rejected text never shows."""

import asyncio
import dataclasses
import json
import tempfile
from pathlib import Path

import pytest
import real
from fastapi.testclient import TestClient
from test_explain_recap import scripted

from matchlens.api import create_app
from matchlens.explain.guard import check, recap_evidence
from matchlens.explain.log import Handoff, HandoffLog, Role, read_handoffs
from matchlens.explain.recap import fallback_recap, recap_case, write_recap
from matchlens.explain.state import Draft, Persona, Reason, ReasonCode, Verdict
from matchlens.render.cues import CueKind
from matchlens.render.recap import FACTS_ONLY, FAN_RECAP, WRITTEN, match_recap


def recap_log(writer, fan=(), seed=7):
    """A recap run's log over match `seed`, with the fan persona."""
    with tempfile.TemporaryDirectory() as tmp:
        log = HandoffLog(Path(tmp) / "recap.jsonl")
        coro = write_recap(
            real.match(seed),
            scripted(writer, fan),
            log,
            run_id="r1",
            personas=(Persona.FAN,),
            whole=real.facts(seed),
        )
        out = asyncio.run(coro)
        return out, read_handoffs(log.path)


def replay(handoffs, seed=7):
    return match_recap(real.match(seed), handoffs, real.facts(seed))


def closed(handoffs) -> Handoff:
    (h,) = [h for h in handoffs if h.receiver is Role.RENDER]
    return h


def swap(handoffs, case):
    last = closed(handoffs)
    return [Handoff(h.ts, h.sender, h.receiver, case) if h is last else h for h in handoffs]


def test_a_written_recap_and_its_fan_rendition_show_with_their_evidence():
    out, handoffs = recap_log(["pass"], ["pass"])
    recap = replay(handoffs)
    cue = recap.cue()
    case = out.case
    assert cue.kind is CueKind.RECAP and cue.due == (2, case.end_ms) and cue.ttl_ms == 20_000
    assert cue.cue_id == f"m7/cue/recap/{case.trigger_ids[0]}"
    assert cue.lines == (WRITTEN, out.cue.text) and cue.event_ids == case.trigger_ids
    assert cue.fact_ids == ("m7/score/match/all",)
    assert cue.rendition("fan").lines == (FAN_RECAP, out.for_persona("fan").text)
    doc = recap.to_dict()
    assert doc["display_clock"] == "90+3:22" and doc["due"] == [2, case.end_ms]
    assert doc["personas"]["analyst"] == {
        "label": "Recap",
        "source": "recap_writer",
        "text": out.cue.text,
        "claims": [c.to_dict() for c in out.cue.claims],
        "fact_ids": ["m7/score/match/all"],
        "event_ids": list(case.trigger_ids),
    }
    assert doc["personas"]["fan"]["source"] == "persona_editor"
    assert json.loads(json.dumps(doc)) == doc


def test_without_a_run_or_with_a_recap_no_draft_passed_the_facts_show():
    m, whole = real.match(7), real.facts(7)
    case = recap_case(m, "replay", whole)
    facts = fallback_recap(m, case, recap_evidence(m, case, whole))
    _, refused = recap_log(["rejected", "rejected", "rejected"])
    for handoffs in ((), refused):
        recap = replay(handoffs)
        assert recap.texts == {"analyst": (FACTS_ONLY, facts), "fan": (FACTS_ONLY, facts)}
        assert recap.cue().rendition("fan").lines == recap.cue().lines
        assert recap.to_dict()["personas"]["analyst"]["source"] == "engine"


def test_a_logged_recap_the_guard_refuses_now_shows_the_facts_and_takes_its_rendition_along():
    _, handoffs = recap_log(["pass"], ["pass"])
    case = closed(handoffs).case
    last = case.attempts[-1]
    forged = dataclasses.replace(last, draft=Draft("It ends 9–9.", last.draft.claims))
    case = dataclasses.replace(case, attempts=(forged,))
    assert case.narrative.text == "It ends 9–9."  # the log says it passed
    recap = replay(swap(handoffs, case))
    assert recap.texts["analyst"][0] == FACTS_ONLY
    assert recap.texts["fan"] == recap.texts["analyst"]  # the rendition would pass on its own


def test_a_fan_recap_the_guard_refuses_now_or_the_log_calls_rejected_never_shows():
    _, handoffs = recap_log(["pass"], ["pass"])
    case = closed(handoffs).case
    r = case.renditions[0]
    text = "It ends 9–9."
    forged = dataclasses.replace(
        r, attempts=(dataclasses.replace(r.attempts[0], draft=Draft(text, r.draft.claims)),)
    )
    refused = Verdict(False, (Reason(ReasonCode.TOO_LONG, "logged as refused"),))
    fallback = dataclasses.replace(
        r, attempts=(dataclasses.replace(r.attempts[0], verdict=refused),), outcome="fallback"
    )
    for rendition in (forged, fallback):
        recap = replay(swap(handoffs, case.with_rendition(rendition)))
        assert recap.texts["analyst"][0] == WRITTEN
        assert recap.texts["fan"] == recap.texts["analyst"]


def test_a_recap_log_of_another_match_closed_twice_or_with_other_facts_is_refused():
    """A log is refused for another match, a double close, other triggers or a fact the engine
    does not show; one offered fewer facts (an older offer) still replays."""
    _, handoffs = recap_log(["pass"], ["pass"])
    with pytest.raises(ValueError, match="a handoff of m7 in the log of m3"):
        replay(handoffs, seed=3)
    with pytest.raises(ValueError, match="closed twice"):
        replay([*handoffs, closed(handoffs)])
    case = closed(handoffs).case
    other = dataclasses.replace(case, trigger_ids=case.trigger_ids[:-1])
    with pytest.raises(ValueError, match="not one of m7"):
        replay(swap(handoffs, other))
    forged = [dict(f) | {"display": "9–9"} if f["name"] == "score" else f for f in case.facts]
    with pytest.raises(ValueError, match="is not the engine's fact"):
        replay(swap(handoffs, dataclasses.replace(case, facts=forged)))
    fewer = dataclasses.replace(case, facts=case.facts[1:])
    assert replay(swap(handoffs, fewer)).texts["analyst"][0] == WRITTEN


def test_every_recap_text_shown_passes_the_guard_again():
    for writer, fan in ((["pass"], ["pass"]), (["rejected", "pass"], ["rejected", "rejected"])):
        out, handoffs = recap_log(writer, fan)
        recap = replay(handoffs)
        evidence = recap_evidence(real.match(7), out.case, real.facts(7))
        for _, draft in recap.texts.values():
            assert check(draft, out.case, evidence).passed


# --- the app ------------------------------------------------------------------------------------


def test_the_app_serves_the_recap_and_streams_it_after_the_full_time_cue():
    out, handoffs = recap_log(["pass"], ["pass"])
    m = real.match(7)
    with TestClient(create_app([m], handoffs={"m7": handoffs})) as client:
        doc = client.get("/matches/m7/recap").json()
        body = client.get("/matches/m7/live?speed=0&hz=1").text
        assert client.get("/matches/m9/recap").status_code == 404
    assert doc == replay(handoffs).to_dict()
    assert doc["personas"]["analyst"]["text"] == out.cue.text
    sent = [json.loads(line[6:])["cue"] for line in body.splitlines() if '"cue":' in line]
    assert [c["kind"] for c in sent[-2:]] == ["period_end", "recap"]
    assert sent[-1] == replay(handoffs).cue().to_dict()


def test_an_app_given_its_cues_has_no_recap_endpoint():
    with TestClient(create_app([real.match(7)], cues={"m7": real.cues(7)})) as client:
        r = client.get("/matches/m7/recap")
    assert (r.status_code, r.json()["detail"]) == (404, "no recap of m7")


def test_a_deterministic_recap_the_guard_refuses_is_a_bug_not_a_card(monkeypatch):
    import matchlens.render.recap as render_recap

    monkeypatch.setattr(render_recap, "fallback_recap", lambda m, c, e: Draft("A match.", ()))
    with pytest.raises(RuntimeError, match="deterministic recap of m7 fails the Guard"):
        replay(())


def test_an_app_given_overlays_serves_them_without_computing():
    from matchlens.render.moments import match_overlay

    _, handoffs = recap_log(["pass"], ["pass"])
    m = real.match(7)
    overlay = match_overlay(m, handoffs, real.facts(7))
    app = create_app([m], overlays={"m7": overlay})
    with TestClient(app) as client:
        assert client.get("/matches/m7/recap").json() == overlay.recap.to_dict()
    for clash in ({"cues": {"m7": []}}, {"handoffs": {"m7": handoffs}}):
        with pytest.raises(ValueError, match="two of cues, handoffs and overlays"):
            create_app([m], overlays={"m7": overlay}, **clash)
    with pytest.raises(ValueError, match="overlays of matches not served: m8"):
        create_app([m], overlays={"m8": overlay})

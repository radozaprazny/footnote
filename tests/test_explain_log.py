import dataclasses
import itertools
import json
from datetime import datetime, timedelta

import pytest
from explain_strategies import PASS, REJECT, attempt, case, moment_cases
from hypothesis import assume, given
from hypothesis import strategies as st

from matchlens.explain.log import (
    SCHEMA_VERSION,
    TRANSITIONS,
    Handoff,
    HandoffLog,
    Role,
    read_handoffs,
)
from matchlens.explain.state import MAX_ATTEMPTS, RECAP_ID, Claim, Draft, Persona

FRESH = case()
DRAFTED = FRESH.with_attempt(attempt(1))
REJECTED = DRAFTED.with_verdict(REJECT)
LAST_REJECTED = REJECTED.with_attempt(attempt(2)).with_verdict(REJECT)
LAST_REJECTED = LAST_REJECTED.with_attempt(attempt(MAX_ATTEMPTS)).with_verdict(REJECT)
PASSED = DRAFTED.with_verdict(PASS)
STATS_ONLY = LAST_REJECTED.stats_only()
PERSONA_DUE = PASSED.with_personas([Persona.FAN])
_FAN = PERSONA_DUE.renditions[0]
PERSONA_DRAFTED = PERSONA_DUE.with_rendition(_FAN.with_attempt(attempt(1)))
PERSONA_REJECTED = PERSONA_DUE.with_rendition(_FAN.with_attempt(attempt(1)).with_verdict(REJECT))
PERSONA_RETRIED = PERSONA_REJECTED.with_rendition(
    PERSONA_REJECTED.renditions[0].with_attempt(attempt(2))
)
PERSONA_LAST_REJECTED = PERSONA_RETRIED.with_rendition(
    PERSONA_RETRIED.renditions[0].with_verdict(REJECT)
)
PERSONA_PASSED = PERSONA_DUE.with_rendition(_FAN.with_attempt(attempt(1)).with_verdict(PASS))
PERSONA_FALLBACK = PERSONA_LAST_REJECTED.with_rendition(
    PERSONA_LAST_REJECTED.renditions[0].fallback()
)


def ticks():
    counter = itertools.count()
    return lambda: f"2026-10-20T19:00:00.{next(counter):03d}+00:00"


@st.composite
def handoffs(draw):
    """A case and one route its phase allows (a case that is rejected for the last time and not
    yet stats-only has none: the Guard resolves it before it hands it on)."""
    c = draw(moment_cases())
    routes = [route for route, allowed in TRANSITIONS.items() if allowed(c)]
    assume(routes)
    return draw(st.sampled_from(routes)), c


@given(st.lists(handoffs(), min_size=1, max_size=6))
def test_every_handoff_is_one_line_read_back_in_order(tmp_path_factory, records):
    path = tmp_path_factory.mktemp("run") / "handoffs.jsonl"
    log = HandoffLog(path, clock=ticks())
    written = [log.record(sender, receiver, c) for (sender, receiver), c in records]
    assert len(path.read_text(encoding="utf-8").splitlines()) == len(records)
    assert read_handoffs(path) == written
    assert [(h.sender, h.receiver, h.case) for h in written] == [(*t, c) for t, c in records]


WRITER_ROUTES = [route for route in TRANSITIONS if Role.ANALYST in route]


@given(moment_cases())
def test_only_the_recap_writer_takes_a_recap_and_only_the_analyst_a_moment(c):
    """Each of the Analyst's routes has a twin with the Recap Writer in its place: the same
    phase, a recap only; the Analyst's takes a key moment only."""
    moment = dataclasses.replace(c, moment_id=f"{c.match_id}-k1")
    recap = dataclasses.replace(c, moment_id=RECAP_ID)
    assert len(WRITER_ROUTES) == 3
    for route in WRITER_ROUTES:
        twin = tuple(Role.RECAP_WRITER if r is Role.ANALYST else r for r in route)
        assert TRANSITIONS[route](moment) == TRANSITIONS[twin](recap)
        assert not TRANSITIONS[route](recap) and not TRANSITIONS[twin](moment)


def test_a_line_carries_the_whole_state(tmp_path):
    path = tmp_path / "deep" / "handoffs.jsonl"  # the directory comes on the first record
    HandoffLog(path, clock=lambda: "2026-10-20T19:00:00.000+00:00").record(
        Role.DETECTOR, Role.ANALYST, FRESH
    )
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "v": SCHEMA_VERSION,
        "ts": "2026-10-20T19:00:00.000+00:00",
        "from": "moment_detector",
        "to": "analyst",
        "moment_id": FRESH.moment_id,
        "attempt": 0,
        "state": FRESH.to_dict(),
    }


def test_line_breaks_inside_a_narrative_stay_inside_its_line(tmp_path):
    path = tmp_path / "handoffs.jsonl"
    text = "a\nb\rc\x85d e f\x0bg\x0ch\x1ci"
    draft = Draft(text, (Claim(text, ("m7/goal",), ("m7-e00412",)),))
    c = FRESH.with_attempt(attempt(1, draft=draft))
    HandoffLog(path).record(Role.ANALYST, Role.GUARD, c)
    raw = path.read_bytes()
    assert raw.isascii() and raw.count(b"\n") == 1 and len(raw.decode().splitlines()) == 1
    assert read_handoffs(path)[0].case.attempts[0].draft.text == text


def test_the_default_clock_is_utc_with_an_offset(tmp_path):
    handoff = HandoffLog(tmp_path / "h.jsonl").record(Role.DETECTOR, Role.ANALYST, FRESH)
    assert datetime.fromisoformat(handoff.ts).utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "sender, receiver, c",
    [
        (Role.DETECTOR, Role.GUARD, FRESH),  # no such route
        (Role.DETECTOR, Role.RENDER, FRESH),
        (Role.ANALYST, Role.RENDER, PASSED),  # nothing leaves without the Guard
        (Role.ANALYST, Role.ANALYST, DRAFTED),
        (Role.RENDER, Role.ANALYST, FRESH),
        (Role.DETECTOR, Role.ANALYST, DRAFTED),  # the Detector sends fresh cases only
        (Role.DETECTOR, Role.ANALYST, FRESH.stats_only()),
        (Role.ANALYST, Role.GUARD, FRESH),  # no draft
        (Role.ANALYST, Role.GUARD, REJECTED),  # already judged
        (Role.GUARD, Role.ANALYST, FRESH),  # nothing to retry
        (Role.GUARD, Role.ANALYST, DRAFTED),  # not judged yet
        (Role.GUARD, Role.ANALYST, PASSED),  # a narrative is not retried
        (Role.GUARD, Role.ANALYST, LAST_REJECTED),  # no retry left
        (Role.GUARD, Role.RENDER, REJECTED),  # still open
        (Role.GUARD, Role.RENDER, FRESH),
        ("guard", "nowhere", PASSED),  # not a role
        (Role.GUARD, Role.PERSONA_EDITOR, PASSED),  # no rendition asked for
        (Role.GUARD, Role.PERSONA_EDITOR, REJECTED),  # still the Analyst's
        (Role.GUARD, Role.PERSONA_EDITOR, PERSONA_DRAFTED),  # not judged yet
        (Role.GUARD, Role.PERSONA_EDITOR, PERSONA_LAST_REJECTED),  # no retry left
        (Role.GUARD, Role.PERSONA_EDITOR, PERSONA_PASSED),
        (Role.PERSONA_EDITOR, Role.GUARD, PERSONA_DUE),  # nothing written
        (Role.PERSONA_EDITOR, Role.GUARD, PERSONA_REJECTED),  # already judged
        (Role.PERSONA_EDITOR, Role.RENDER, PERSONA_DRAFTED),  # nothing leaves without the Guard
        (Role.PERSONA_EDITOR, Role.ANALYST, PERSONA_DRAFTED),
        (Role.GUARD, Role.RENDER, PERSONA_DUE),  # a rendition still to write
        (Role.GUARD, Role.RENDER, PERSONA_REJECTED),
        (Role.ANALYST, Role.GUARD, PERSONA_DRAFTED),  # a rendition is the editor's
    ],
)
def test_a_handoff_the_graph_does_not_allow_is_refused_and_not_written(
    tmp_path, sender, receiver, c
):
    path = tmp_path / "run" / "handoffs.jsonl"
    with pytest.raises(ValueError, match="handoff|cannot go"):
        HandoffLog(path).record(sender, receiver, c)
    assert not path.parent.exists()  # not even the directory


@pytest.mark.parametrize(
    "sender, receiver, c",
    [
        (Role.GUARD, Role.PERSONA_EDITOR, PERSONA_DUE),
        (Role.GUARD, Role.PERSONA_EDITOR, PERSONA_REJECTED),  # one retry left
        (Role.PERSONA_EDITOR, Role.GUARD, PERSONA_DRAFTED),
        (Role.PERSONA_EDITOR, Role.GUARD, PERSONA_RETRIED),
        (Role.GUARD, Role.RENDER, PERSONA_PASSED),
        (Role.GUARD, Role.RENDER, PERSONA_FALLBACK),
    ],
)
def test_the_persona_editor_s_routes_are_allowed_in_their_phase(tmp_path, sender, receiver, c):
    handoff = HandoffLog(tmp_path / "h.jsonl").record(sender, receiver, c)
    assert read_handoffs(tmp_path / "h.jsonl") == [handoff]


def test_a_v2_line_reads_without_renditions_and_may_not_have_any(tmp_path):
    path = tmp_path / "handoffs.jsonl"
    old = json.loads(line())
    del old["state"]["renditions"], old["state"]["translations"]
    path.write_text(json.dumps(old | {"v": 2}) + "\n", encoding="utf-8")
    (h,) = read_handoffs(path)
    assert h.case == PASSED and h.case.renditions == ()
    path.write_text(line(v=2) + "\n", encoding="utf-8")  # v2 with a renditions key
    with pytest.raises(ValueError, match="v2 case with renditions"):
        read_handoffs(path)
    path.write_text(json.dumps(old | {"v": 3}) + "\n", encoding="utf-8")  # v3 without the key
    with pytest.raises(ValueError, match="v3 case without renditions"):
        read_handoffs(path)


def test_a_v3_line_reads_without_translations_and_may_not_have_any(tmp_path):
    path = tmp_path / "handoffs.jsonl"
    old = json.loads(line())
    del old["state"]["translations"]
    path.write_text(json.dumps(old | {"v": 3}) + "\n", encoding="utf-8")
    (h,) = read_handoffs(path)
    assert h.case == PASSED and h.case.translations == ()
    path.write_text(line(v=3) + "\n", encoding="utf-8")  # v3 with a translations key
    with pytest.raises(ValueError, match="v3 case with translations"):
        read_handoffs(path)
    path.write_text(json.dumps(old | {"v": 4}) + "\n", encoding="utf-8")  # v4 without the key
    with pytest.raises(ValueError, match="v4 case without translations"):
        read_handoffs(path)


def test_roles_given_as_strings_are_read_as_roles(tmp_path):
    handoff = HandoffLog(tmp_path / "h.jsonl").record("guard", "render", STATS_ONLY)
    assert (handoff.sender, handoff.receiver) == (Role.GUARD, Role.RENDER)


def test_a_fact_that_is_not_strict_json_is_refused_and_not_written(tmp_path):
    path = tmp_path / "handoffs.jsonl"
    with pytest.raises(ValueError, match="no strict JSON"):  # the case refuses it already
        nan = {"fact_id": "m7/speed", "display": "28 m/s", "value": float("nan")}
        HandoffLog(path).record(Role.DETECTOR, Role.ANALYST, case(facts=(nan,)))
    assert not path.exists()


def line(**changes) -> str:
    good = Handoff("2026-10-20T19:00:00.000+00:00", Role.GUARD, Role.RENDER, PASSED).to_dict()
    return json.dumps({k: v for k, v in (good | changes).items() if v is not ...})


@pytest.mark.parametrize(
    "bad",
    [
        line(moment_id="m0-k0"),  # the summary contradicts the state
        line(attempt=0),
        line(**{"from": "analyst"}),  # a route the graph does not have
        line(state=REJECTED.to_dict(), attempt=1),  # an open case at render
        line(extra=1),
        line(ts=...),  # missing
        line(ts=5),
        line(ts=""),
        line(ts="2026-10-20T21:00:00.000+02:00"),  # the log writes UTC
        line(ts="2026-10-20T19:00:00"),  # no offset
        line(v=SCHEMA_VERSION + 1),
        line(v=1),  # an older log
        line(v=True),
        line(v=...),
        line(attempt=True),  # bool is no count
        line(attempt=1.0),
        line().replace('"display": "1-0"', '"display": "1-0", "speed": NaN'),
        line().replace('"from": "guard"', '"from": "guard", "from": "guard"'),
        "[1, 2]",
    ],
)
def test_a_line_the_log_could_not_have_written_is_refused_on_reading(tmp_path, bad):
    path = tmp_path / "handoffs.jsonl"
    path.write_text(bad + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_handoffs(path)


def test_blank_lines_are_skipped(tmp_path):
    path = tmp_path / "handoffs.jsonl"
    path.write_text(f"\n{line()}\n  \n{line()}\n", encoding="utf-8")
    assert [h.case for h in read_handoffs(path)] == [PASSED, PASSED]


def test_a_reading_error_names_its_line(tmp_path):
    path = tmp_path / "handoffs.jsonl"
    path.write_text(f"{line()}\n\n{line(attempt=0)}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"handoffs.jsonl:3: "):
        read_handoffs(path)


def test_a_handoff_needs_a_case():
    with pytest.raises(ValueError, match="the case is a dict"):
        Handoff("2026-10-20T19:00:00.000+00:00", Role.GUARD, Role.RENDER, PASSED.to_dict())


def test_a_line_that_is_no_utf8_is_refused_with_its_number(tmp_path):
    path = tmp_path / "handoffs.jsonl"
    path.write_bytes(line().encode() + b"\n" + b'{"v": 1, "ts": "\xff"}\n')
    with pytest.raises(ValueError, match=r"handoffs.jsonl:2: "):
        read_handoffs(path)

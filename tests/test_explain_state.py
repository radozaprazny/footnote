import dataclasses
import json

import pytest
from explain_strategies import DRAFT, NO_DRAFT, PASS, REJECT, attempt, case, moment_cases
from hypothesis import given

from matchlens.explain.state import (
    MAX_ATTEMPTS,
    Attempt,
    CallError,
    CallFailure,
    Claim,
    Draft,
    MomentCase,
    MomentOutcome,
    Persona,
    Reason,
    Rendition,
    RenditionOutcome,
    Verdict,
)

TIMEOUT = CallFailure(CallError.TIMEOUT, "no answer in 30 s")


@given(moment_cases())
def test_a_case_survives_json(c):
    assert MomentCase.from_dict(json.loads(json.dumps(c.to_dict()))) == c


def test_the_api_walks_a_case_to_a_narrative():
    c = case()
    for n in range(1, MAX_ATTEMPTS):
        c = c.with_attempt(attempt(n)).with_verdict(REJECT)
        assert c.is_open
    c = c.with_attempt(attempt(MAX_ATTEMPTS)).with_verdict(PASS)
    assert c.outcome is MomentOutcome.NARRATIVE and not c.is_open


def test_the_api_walks_a_case_to_stats_only():
    c = case().with_attempt(attempt(1, draft=None)).with_verdict(NO_DRAFT).stats_only()
    assert c.outcome is MomentOutcome.STATS_ONLY
    assert c.attempts[0].called_model
    skipped = Attempt(1, "fake", None, error=CallFailure("skipped", "circuit breaker open"))
    assert not skipped.called_model and skipped.error.code is CallError.SKIPPED


@pytest.mark.parametrize(
    "changes",
    [
        {"outcome": MomentOutcome.NARRATIVE},  # nothing passed
        {"attempts": (attempt(1, REJECT),), "outcome": MomentOutcome.NARRATIVE},
        {"attempts": (attempt(1, PASS),)},  # passed, still pending
        {"attempts": (attempt(1, PASS),), "outcome": MomentOutcome.STATS_ONLY},
        {"attempts": (attempt(1),), "outcome": MomentOutcome.STATS_ONLY},  # unjudged
        {"attempts": (attempt(1), attempt(2))},  # an unjudged attempt before the last
        {"attempts": (attempt(1, PASS), attempt(2))},  # an attempt after a pass
        {"attempts": (attempt(2),)},  # numbering
        {"attempts": tuple(attempt(n, REJECT) for n in range(1, MAX_ATTEMPTS + 2))},
        {"trigger_ids": ()},
        {"period": 3},
        {"start_ms": 10, "end_ms": 9},
        {"end_ms": 3_600_001, "display_clock": "90+15:00"},  # past the longest period
        {"display_clock": "67:10"},  # the clock at end_ms is 67:23
        {"trigger_ids": ("m7-e00412", "m7-e00412")},
        {"trigger_ids": ("m8-e00412",)},  # an event of another match
        {"trigger_ids": ("m7-f000412",)},  # a frame is no trigger
        {"facts": ({"fact_id": "m7/goal", "display": "1-0"},) * 2},  # duplicate fact ids
        {"facts": ({"fact_id": "m7/goal"},)},  # no display
        {"facts": ({"fact_id": "m7/goal", "display": 1},)},
        {"facts": ({"fact_id": "m7/goal", "display": "1-0", "ids": {"m7-e1"}},)},  # no JSON
        {"facts": ({"fact_id": "m7/goal", "display": "1-0", "speed": float("nan")},)},
    ],
)
def test_an_inconsistent_case_is_refused(changes):
    with pytest.raises(ValueError):
        case(**changes)


def test_the_parts_refuse_contradictions():
    with pytest.raises(ValueError, match="no reasons"):
        Verdict(True, REJECT.reasons)
    with pytest.raises(ValueError, match="no reasons"):
        Verdict(False)
    with pytest.raises(ValueError, match="exactly one"):
        Attempt(1, "fake", DRAFT, error=TIMEOUT)
    with pytest.raises(ValueError, match="exactly one"):
        Attempt(1, "fake", None)
    with pytest.raises(ValueError, match="cannot pass"):
        Attempt(1, "fake", None, error=TIMEOUT, verdict=PASS)
    with pytest.raises(ValueError, match="point at claims"):
        Attempt(1, "fake", None, error=TIMEOUT, verdict=REJECT)  # claim 0 of no draft
    with pytest.raises(ValueError, match="point at claims"):
        attempt(1, Verdict(False, (Reason("number_not_cited", "x", "1", 1),)))  # 1 claim only
    with pytest.raises(ValueError, match="not an int"):
        Attempt(True, "fake", DRAFT)  # bool is no attempt number
    with pytest.raises(ValueError, match="already judged"):
        attempt(1, REJECT).judged(PASS)
    with pytest.raises(ValueError, match="no attempt"):
        case().with_verdict(PASS)
    closed = case().with_attempt(attempt(1)).with_verdict(PASS)
    with pytest.raises(ValueError, match="already judged"):
        closed.with_verdict(REJECT)


def test_from_dict_wants_exactly_the_fields():
    data = case().to_dict()
    with pytest.raises(ValueError, match="missing keys: outcome"):
        MomentCase.from_dict({k: v for k, v in data.items() if k != "outcome"})
    with pytest.raises(ValueError, match="unknown keys: extra"):
        MomentCase.from_dict(data | {"extra": 1})
    with pytest.raises(ValueError, match="JSON object"):
        Draft.from_dict(["text", []])


def test_a_narrative_is_only_the_draft_that_passed():
    rejected = case().with_attempt(attempt(1)).with_verdict(REJECT)
    assert rejected.narrative is None and rejected.stats_only().narrative is None
    other = Draft("Corrowmere lead 1-0.", (Claim("lead 1-0", ("m7/goal",), ("m7-e00412",)),))
    passed = rejected.with_attempt(attempt(2, draft=other)).with_verdict(PASS)
    assert passed.narrative == other  # the last draft, not the rejected one before it


def test_a_closed_case_takes_no_further_attempt():
    passed = case().with_attempt(attempt(1)).with_verdict(PASS)
    stats_only = case().with_attempt(attempt(1)).with_verdict(REJECT).stats_only()
    for closed in (passed, stats_only):
        with pytest.raises(ValueError, match="closed"):
            closed.with_attempt(attempt(2, REJECT))


def test_sequences_are_stored_as_tuples_so_a_case_cannot_change_after_its_checks():
    c = case(attempts=[attempt(1, PASS)], trigger_ids=["m7-e00412"], outcome="narrative")
    assert type(c.attempts) is tuple and type(c.trigger_ids) is tuple and type(c.facts) is tuple
    assert c.outcome is MomentOutcome.NARRATIVE
    verdict = Verdict(False, [REJECT.reasons[0]])
    assert type(verdict.reasons) is tuple and type(DRAFT.claims[0].fact_ids) is tuple


@pytest.mark.parametrize(
    "build",
    [
        lambda: case(trigger_ids="m7-e00412"),  # a string is no list of ids
        lambda: case(facts="abc"),
        lambda: case(facts=("abc",)),
        lambda: case(attempts=({"n": 1},)),
        lambda: case(outcome="won"),
        lambda: case(period=True),  # bool is no int
        lambda: case(start_ms=-1),
        lambda: case(start_ms="5"),
        lambda: case(end_ms=float("inf")),
        lambda: case(match_id=7),
        lambda: Verdict(1),  # JSON's 1 is no pass
        lambda: Verdict(False, "no_draft"),
        lambda: Attempt(0, "fake", DRAFT),
        lambda: Attempt(1, "fake", DRAFT, tokens_in=-1),
        lambda: Attempt(1, "fake", DRAFT, tokens_out=-1),
        lambda: Attempt(1, "fake", DRAFT, latency_ms=-1),
        lambda: Attempt(1, "fake", DRAFT, requests=-1),
        lambda: Attempt(1, "fake", DRAFT, requests=True),  # bool is no count
        lambda: Attempt(1, "fake", "a draft"),
        lambda: Attempt(1, "fake", DRAFT, verdict=True),
        lambda: Attempt(1, "fake", None, error="timeout"),  # a failure has a code
        lambda: CallFailure("lost", "x"),
        lambda: CallFailure(CallError.TIMEOUT, None),
        lambda: Draft("text", "claims"),
        lambda: Draft(None, ()),
        lambda: Reason("no_draft", "x", claim=-1),
        lambda: Reason("no_draft", "x", claim=True),
        lambda: Reason("no_draft", "x", token=5),
        lambda: Reason(None, "x"),
    ],
)
def test_wrong_types_are_refused(build):
    with pytest.raises(ValueError):
        build()


def test_an_attempt_is_judged_once():
    for verdict in (PASS, REJECT):
        with pytest.raises(ValueError, match="already judged"):
            attempt(1, verdict).judged(REJECT)


def test_from_dict_refuses_json_that_only_looks_right():
    good = case().with_attempt(attempt(1)).with_verdict(PASS).to_dict()
    bad = [
        good | {"trigger_ids": "m7-e00412"},
        good | {"attempts": {"n": 1}},
        good | {"attempts": [good["attempts"][0] | {"verdict": {"passed": 1, "reasons": []}}]},
    ]
    for data in bad:
        with pytest.raises(ValueError):
            MomentCase.from_dict(data)


def test_facts_are_copies_of_what_came_in():
    source = {"fact_id": "m7/goal", "display": "1-0", "event_ids": ("m7-e00412",)}
    c = case(facts=(source,))
    source["display"] = "2-0"
    assert c.facts[0] == {"fact_id": "m7/goal", "display": "1-0", "event_ids": ["m7-e00412"]}
    c.to_dict()["facts"][0]["display"] = "3-0"
    assert c.facts[0]["display"] == "1-0"
    assert MomentCase.from_dict(json.loads(json.dumps(c.to_dict()))) == c


def test_every_part_is_frozen():
    passed = case().with_attempt(attempt(1)).with_verdict(PASS)
    parts = [passed, passed.attempts[0], DRAFT, DRAFT.claims[0], REJECT, REJECT.reasons[0], TIMEOUT]
    for part in parts:
        name = dataclasses.fields(part)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(part, name, getattr(part, name))


@pytest.mark.parametrize("name", ["fact_ids", "event_ids", "frame_ids"])
def test_a_claim_refuses_a_string_for_its_ids(name):
    with pytest.raises(ValueError, match="must be a list"):
        Claim(**{"text": "t", "fact_ids": (), "event_ids": ()} | {name: "m7-e00412"})


@pytest.mark.parametrize(
    "cls, data",
    [
        (Claim, DRAFT.claims[0].to_dict()),
        (Reason, REJECT.reasons[0].to_dict()),
        (Verdict, REJECT.to_dict()),
        (CallFailure, TIMEOUT.to_dict()),
        (Attempt, attempt(1, REJECT).to_dict()),
        (Draft, DRAFT.to_dict()),
        (Rendition, Rendition(Persona.FAN, (attempt(1, PASS),), "passed").to_dict()),
    ],
)
def test_every_part_reads_exactly_its_keys(cls, data):
    assert cls.from_dict(data).to_dict() == data
    first = next(iter(data))
    with pytest.raises(ValueError, match="missing keys"):
        cls.from_dict({k: v for k, v in data.items() if k != first})
    with pytest.raises(ValueError, match="unknown keys"):
        cls.from_dict(data | {"extra": 1})


def test_a_list_field_that_is_no_json_array_is_refused():
    good = case().with_attempt(attempt(1)).with_verdict(PASS).to_dict()
    with pytest.raises(ValueError, match="JSON array"):
        MomentCase.from_dict(good | {"attempts": 5})


# --- renditions (M5) ---------------------------------------------------------------------------


def narrative_case() -> MomentCase:
    return case().with_attempt(attempt(1)).with_verdict(PASS)


FAN_DRAFT = Draft("Corrowmere score.", (Claim("Corrowmere score", ("m7/goal",), ("m7-e00412",)),))


def test_the_api_walks_a_rendition_to_passed_and_to_fallback():
    c = narrative_case().with_personas(["fan"])
    (r,) = c.renditions
    assert r.persona is Persona.FAN and r.is_open and c.pending_rendition == r
    assert c.rendition("fan") is None  # still open
    r = r.with_attempt(attempt(1, draft=FAN_DRAFT))
    assert not r.can_retry  # not judged yet
    r = r.with_verdict(REJECT)
    assert r.can_retry and r.is_open
    passed = r.with_attempt(attempt(2, draft=FAN_DRAFT)).with_verdict(PASS)
    assert passed.outcome is RenditionOutcome.PASSED and passed.draft == FAN_DRAFT
    done = c.with_rendition(passed)
    assert done.pending_rendition is None and done.rendition("fan") == FAN_DRAFT
    fell = c.with_rendition(
        r.with_attempt(attempt(2, draft=None)).with_verdict(NO_DRAFT).fallback()
    )
    assert fell.rendition(Persona.FAN) == fell.narrative and fell.renditions[0].draft is None
    assert MomentCase.from_dict(json.loads(json.dumps(fell.to_dict()))) == fell


def test_a_rendition_refuses_contradictions():
    a1, a2 = attempt(1, REJECT, FAN_DRAFT), attempt(2, PASS, FAN_DRAFT)
    bad = [
        ({"attempts": (attempt(2, REJECT),)}, "numbered"),
        ({"attempts": (a1, dataclasses.replace(a2, verdict=REJECT), attempt(3))}, "at most 2"),
        ({"attempts": (attempt(1, PASS), attempt(2))}, "judged and rejected"),
        ({"attempts": (a1, a2)}, "the last attempt passed"),  # passed, but outcome pending
        ({"attempts": (attempt(1),), "outcome": "fallback"}, "not judged"),
        ({"attempts": (a1,), "outcome": "passed"}, "the last attempt passed"),
        ({"persona": "pundit"}, "pundit"),
        ({"outcome": "won"}, "won"),
    ]
    for changes, message in bad:
        with pytest.raises(ValueError, match=message):
            Rendition(**({"persona": "fan"} | changes))


def test_renditions_belong_to_a_narrative_once_per_persona():
    fan = Rendition(Persona.FAN)
    with pytest.raises(ValueError, match="no narrative"):
        case(renditions=(fan,))
    with pytest.raises(ValueError, match="one persona"):
        dataclasses.replace(narrative_case(), renditions=(fan, fan))
    with pytest.raises(ValueError, match="only once"):
        narrative_case().with_personas(["fan"]).with_personas(["fan"])
    with pytest.raises(ValueError, match="only once"):
        case().with_personas(["fan"])
    with pytest.raises(ValueError, match="no rendition"):
        narrative_case().with_rendition(fan)
    closed = Rendition(Persona.FAN).fallback()
    with pytest.raises(ValueError, match="closed"):
        closed.with_attempt(attempt(1))
    with pytest.raises(ValueError, match="closed"):
        closed.fallback()


def test_a_case_logged_before_renditions_reads_with_none():
    data = narrative_case().to_dict()
    del data["renditions"]
    assert MomentCase.from_dict(data) == narrative_case()
    with pytest.raises(ValueError, match="JSON array"):
        MomentCase.from_dict(narrative_case().to_dict() | {"renditions": 5})

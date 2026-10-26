"""Hypothesis strategies for the Explain stage's shared state (every draw is a valid case), and
fixed examples for tests that need one case."""

import dataclasses

from hypothesis import strategies as st
from strategies import match_ids

from matchlens.events import (
    FRAMES_PER_PERIOD,
    MAX_PERIOD_MS,
    MAX_SEQ,
    display_clock,
    make_event_id,
    make_frame_id,
)
from matchlens.explain.state import (
    ANALYST,
    MAX_ATTEMPTS,
    PERSONA_ATTEMPTS,
    RECAP_ID,
    TRANSLATION_ATTEMPTS,
    Attempt,
    CallError,
    CallFailure,
    Claim,
    Draft,
    Lang,
    MomentCase,
    MomentOutcome,
    Persona,
    Reason,
    ReasonCode,
    Rendition,
    RenditionOutcome,
    Translation,
    Verdict,
)

counts = st.integers(0, 10**6)
seqs = st.integers(0, MAX_SEQ)


def event_ids(match_id: str):
    return seqs.map(lambda seq: make_event_id(match_id, seq))


def frame_ids(match_id: str):
    return st.builds(
        lambda period, frame: make_frame_id(match_id, period, frame * 100),
        st.sampled_from([1, 2]),
        st.integers(0, FRAMES_PER_PERIOD - 1),
    )


json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(-(10**9), 10**9)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=8),
    lambda inner: (
        st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner, max_size=3)
    ),
    max_leaves=6,
)


def facts(match_id: str):
    """Fact payloads with unique ids; besides `fact_id` and `display`, any JSON."""

    def fact(fact_id: str, display: str, extra: dict) -> dict:
        return extra | {"fact_id": fact_id, "display": display}

    ids = st.from_regex(r"[a-z_.]{1,12}", fullmatch=True).map(lambda name: f"{match_id}/{name}")
    extras = st.dictionaries(st.text(max_size=8), json_values, max_size=3)
    return st.lists(ids, max_size=3, unique=True).flatmap(
        lambda fact_ids: st.tuples(
            *(st.builds(fact, st.just(i), st.text(max_size=8), extras) for i in fact_ids)
        )
    )


def claims(match_id: str):
    return st.builds(
        Claim,
        st.text(max_size=40),
        st.lists(st.from_regex(r"m[0-9]{1,2}/[a-z_.]{1,12}", fullmatch=True), max_size=3),
        st.lists(event_ids(match_id), max_size=3),
        st.lists(frame_ids(match_id), max_size=2),
    )


reasons = st.builds(
    Reason,
    st.sampled_from(ReasonCode),
    st.text(max_size=40),
    st.none() | st.text(max_size=8),
    st.none(),  # a claim index needs the draft: `attempts` adds one where it fits
)
rejections = st.builds(Verdict, st.just(False), st.lists(reasons, min_size=1, max_size=3))
failures = st.builds(CallFailure, st.sampled_from(CallError), st.text(min_size=1, max_size=20))
PASS = Verdict(True)


@st.composite
def attempts(draw, match_id: str, n: int, verdict: Verdict | None) -> Attempt:
    failed = verdict is None or not verdict.passed
    error = draw(st.none() | failures) if failed else None
    draft = draw(st.builds(Draft, st.text(max_size=80), st.lists(claims(match_id), max_size=3)))
    if error is not None:
        draft = None
    elif verdict is not None and not verdict.passed and draft.claims:
        index = draw(st.integers(0, len(draft.claims) - 1))
        first = dataclasses.replace(verdict.reasons[0], claim=index)
        verdict = Verdict(False, (first, *verdict.reasons[1:]))
    return Attempt(
        n=n,
        model=draw(st.sampled_from(["claude-sonnet-5-5", "claude-haiku-5-5", "fake"])),
        draft=draft,
        error=error,
        verdict=verdict,
        tokens_in=draw(counts),
        tokens_out=draw(counts),
        latency_ms=draw(counts),
        requests=draw(st.integers(0, 2)),
    )


@st.composite
def _rewritten(draw, match_id: str, limit: int) -> tuple[tuple[Attempt, ...], RenditionOutcome]:
    """Attempts at a rendition or a translation at any point of its way, and its outcome."""
    n = draw(st.integers(0, limit))
    tried = [draw(attempts(match_id, i, draw(rejections))) for i in range(1, n)]
    if n:
        last = draw(st.none() | st.just(PASS) | rejections)
        tried.append(draw(attempts(match_id, n, last)))
    if tried and tried[-1].verdict is not None and tried[-1].verdict.passed:
        outcome = RenditionOutcome.PASSED
    elif tried and tried[-1].verdict is None:
        outcome = RenditionOutcome.PENDING
    else:
        outcome = draw(st.sampled_from([RenditionOutcome.PENDING, RenditionOutcome.FALLBACK]))
    return tuple(tried), outcome


@st.composite
def renditions(draw, match_id: str, persona: Persona = Persona.FAN) -> Rendition:
    """A rendition at any point of its way: none written, waiting for the Guard, to be written
    again, passed or fallen back to the narrative."""
    return Rendition(persona, *draw(_rewritten(match_id, PERSONA_ATTEMPTS)))


@st.composite
def translations(draw, match_id: str, persona: str = ANALYST) -> Translation:
    """A translation at any point of its way: none written, waiting for the Guard, to be written
    again, passed or fallen back to the English text."""
    lang = draw(st.sampled_from(Lang))
    return Translation(lang, persona, *draw(_rewritten(match_id, TRANSLATION_ATTEMPTS)))


@st.composite
def moment_cases(draw) -> MomentCase:
    """A case at any point of its way: no attempt yet, waiting for the Guard, retrying, or done;
    a narrative with or without its renditions, and once they are closed with or without the
    translations of its texts; a key moment's or the match's recap."""
    match_id = draw(match_ids)
    n = draw(st.integers(0, MAX_ATTEMPTS))
    tried = [draw(attempts(match_id, i, draw(rejections))) for i in range(1, n)]
    if n:
        last = draw(st.none() | st.just(PASS) | rejections)
        tried.append(draw(attempts(match_id, n, last)))
    if tried and tried[-1].verdict is not None and tried[-1].verdict.passed:
        outcome = MomentOutcome.NARRATIVE
    elif tried and tried[-1].verdict is None:
        outcome = MomentOutcome.PENDING
    else:
        outcome = draw(st.sampled_from([MomentOutcome.PENDING, MomentOutcome.STATS_ONLY]))
    period = draw(st.sampled_from([1, 2]))
    end = draw(st.integers(0, MAX_PERIOD_MS))
    narrated = outcome is MomentOutcome.NARRATIVE
    written = tuple(draw(st.lists(renditions(match_id), max_size=1)) if narrated else ())
    own = [ANALYST, *(r.persona.value for r in written if r.draft is not None)]
    translated = ()
    if narrated and not any(r.is_open for r in written):
        whose = draw(st.lists(st.sampled_from(own), unique=True))
        translated = tuple(draw(translations(match_id, p)) for p in whose)
    return MomentCase(
        run_id=draw(st.from_regex(r"r[0-9]{1,4}", fullmatch=True)),
        match_id=match_id,
        moment_id=draw(st.sampled_from([f"{match_id}-k{draw(st.integers(0, 999))}", RECAP_ID])),
        trigger_ids=draw(st.lists(event_ids(match_id), min_size=1, max_size=3, unique=True)),
        period=period,
        start_ms=end - draw(st.integers(0, min(end, 60_000))),
        end_ms=end,
        display_clock=display_clock(period, end),
        facts=draw(facts(match_id)),
        attempts=tuple(tried),
        outcome=outcome,
        renditions=written,
        translations=translated,
    )


REJECT = Verdict(False, (Reason("number_not_cited", "67 is not in a cited fact", "67", 0),))
NO_DRAFT = Verdict(False, (Reason("no_draft", "timeout: no answer in 30 s"),))
DRAFT = Draft(
    "Corrowmere score in the 68th minute.",
    (Claim("Corrowmere score in the 68th minute", ("m7/goal", "m7/minute"), ("m7-e00412",)),),
)


def case(**changes) -> MomentCase:
    """A goal in match 7 at 67:23 with no attempt yet; `changes` replace fields."""
    base = MomentCase(
        run_id="r1",
        match_id="m7",
        moment_id="m7-k1",
        trigger_ids=("m7-e00411", "m7-e00412"),
        period=2,
        start_ms=1_330_000,
        end_ms=1_343_000,
        display_clock="67:23",
        facts=(
            {"fact_id": "m7/goal", "display": "1-0"},
            {"fact_id": "m7/minute", "display": "68th"},
        ),
    )
    return dataclasses.replace(base, **changes)


def attempt(n: int, verdict: Verdict | None = None, draft: Draft | None = DRAFT) -> Attempt:
    """Attempt `n` with the example draft, or a timed-out call when `draft` is None."""
    error = CallFailure(CallError.TIMEOUT, "no answer in 30 s") if draft is None else None
    return Attempt(n, "fake", draft, error=error, verdict=verdict)

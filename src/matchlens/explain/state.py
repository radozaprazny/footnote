"""The shared state the Explain agents hand each other: one `MomentCase` per key moment.

A case starts at the Moment Detector with the moment's facts, collects one `Attempt` per Analyst
draft, gets each attempt judged by the Guard, and ends as a narrative or as a stats-only cue. The
checks below make an unverified narrative unrepresentable: a case ends as a narrative only when
its last attempt passed the Guard, and a closed case takes no further attempt. A narrative then
gets one `Rendition` per persona the run asks for (M5): the Persona Editor's attempts at it, each
judged by the Guard, ending as the persona's own draft that passed or, failing that, as the
Analyst's narrative (`fallback`); a rendition is passed only when its last attempt passed. Once
every rendition is closed, each text a persona reads that the agents wrote (the narrative, a
persona's own draft) may get one `Translation` per language: the Translator's attempts, each
judged by the Guard in that language against its source, ending as the translation that passed
or, failing that, as the source text in English (`fallback`).
Every class round-trips through JSON (`to_dict` / `from_dict`), because the whole case is
logged at every handoff. Sequences are stored as tuples (a list is converted, a string refused)
and facts as normalized JSON copies, so what a caller passes in or reads out cannot change a
case; the fact dicts themselves stay dicts, and nothing may mutate them.
"""

import copy
import json
from collections.abc import Sequence
from dataclasses import dataclass, fields, replace
from enum import StrEnum
from typing import Any, Self

from matchlens.events import MAX_PERIOD_MS, PERIODS, display_clock, parse_event_id

MAX_ATTEMPTS = 3  # the first draft and at most 2 retries
RECAP_ID = "recap"  # the moment id of a match's recap at full time (`explain.recap`)
PERSONA_ATTEMPTS = 2  # a rendition's first draft and at most 1 retry
TRANSLATION_ATTEMPTS = 2  # a translation's first draft and at most 1 retry
ANALYST = "analyst"  # the persona that reads the narrative itself
DEFAULT_MAX_CALLS = 40  # model calls per run: Azure budgets only alert, they stop nothing


class Persona(StrEnum):
    """Who a rendition is for; the analyst persona is the Analyst's narrative itself."""

    FAN = "fan"  # a casual fan: short, plain words, a reading's phrase over a percentage


class Lang(StrEnum):
    """A language a passed text is translated into; the agents write in English."""

    SK = "sk"


class RenditionOutcome(StrEnum):
    PENDING = "pending"
    PASSED = "passed"  # the last attempt passed the Guard
    FALLBACK = "fallback"  # no attempt passed: the Analyst's narrative stands in


class MomentOutcome(StrEnum):
    PENDING = "pending"
    NARRATIVE = "narrative"  # the last attempt passed the Guard
    STATS_ONLY = "stats_only"  # no attempt passed: the cue carries facts only


@dataclass(frozen=True)
class Claim:
    """One statement of a draft and what backs it: fact ids, and the event ids or (for a tracking
    value) frame ids the facts come from. Whether they are right is the Guard's to judge."""

    text: str
    fact_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    frame_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _strs(self, "claim", "text")
        for name in ("fact_ids", "event_ids", "frame_ids"):
            _tuple(self, name, str, "claim")

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "fact_ids": list(self.fact_ids),
            "event_ids": list(self.event_ids),
            "frame_ids": list(self.frame_ids),
        }

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        _check_keys(data, cls)
        return cls(**data)


@dataclass(frozen=True)
class Draft:
    """What the Analyst writes: the narrative text and the claims it is made of."""

    text: str
    claims: tuple[Claim, ...]

    def __post_init__(self) -> None:
        _strs(self, "draft", "text")
        _tuple(self, "claims", Claim, "draft")

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "claims": [c.to_dict() for c in self.claims]}

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        _check_keys(data, cls)
        return cls(data["text"], _items(data["claims"], Claim, "draft claims"))


class ReasonCode(StrEnum):
    """Why the Guard rejects a draft (`matchlens.explain.guard` has the rules)."""

    NO_DRAFT = "no_draft"  # the attempt failed: no draft to judge
    NO_CLAIMS = "no_claims"
    CLAIM_NOT_IN_TEXT = "claim_not_in_text"
    UNKNOWN_FACT = "unknown_fact"
    NUMBER_NOT_CITED = "number_not_cited"
    NUMBER_OUTSIDE_CLAIM = "number_outside_claim"
    NUMBER_WORD = "number_word"
    NO_EVIDENCE = "no_evidence"
    UNKNOWN_EVENT = "unknown_event"
    UNKNOWN_FRAME = "unknown_frame"
    FOREIGN_ID = "foreign_id"
    UNKNOWN_NAME = "unknown_name"
    UNREADABLE_NUMBER = "unreadable_number"  # a numeric character other than 0-9: ½, ², Ⅲ
    SCOPE_NOT_NAMED = "scope_not_named"  # a fact of the last minutes without its window
    PHRASE_OUTSIDE_CLAIM = "phrase_outside_claim"  # a reading's phrase in no claim
    PHRASE_NOT_CITED = "phrase_not_cited"  # no cited reading of the team named shows the phrase
    JUDGEMENT_WORD = "judgement_word"  # a judgement of the score or the play that is no phrase
    TOO_LONG = "too_long"  # over the Guard's limits of characters or claims
    NO_FINAL_SCORE = "no_final_score"  # a recap whose claims do not state the final score
    NUMERAL_CHANGED = "numeral_changed"  # a translation's numerals are not its source's
    NAME_CHANGED = "name_changed"  # a translation's names are not its source's


@dataclass(frozen=True)
class Reason:
    """Why the Guard rejected a draft, machine-readable; `detail` goes back to the Analyst."""

    code: ReasonCode
    detail: str
    token: str | None = None  # the offending number, id or name, when there is one
    claim: int | None = None  # index of the claim it is in

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "code", ReasonCode(self.code))
        except ValueError:
            raise ValueError(f"reason: {self.code!r} is not a ReasonCode") from None
        _strs(self, "reason", "detail")
        if self.token is not None:
            _strs(self, "reason", "token")
        if self.claim is not None:
            _int(self.claim, 0, "reason: claim")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "detail": self.detail,
            "token": self.token,
            "claim": self.claim,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        _check_keys(data, cls)
        return cls(**data)


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reasons: tuple[Reason, ...] = ()

    def __post_init__(self) -> None:
        if type(self.passed) is not bool:
            raise ValueError(f"verdict: passed = {self.passed!r} is not a bool")
        _tuple(self, "reasons", Reason, "verdict")
        if self.passed == bool(self.reasons):
            raise ValueError("a verdict passes exactly when it has no reasons")

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "reasons": [r.to_dict() for r in self.reasons]}

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        _check_keys(data, cls)
        return cls(data["passed"], _items(data["reasons"], Reason, "verdict reasons"))


class CallError(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    TRANSPORT = "transport"  # no answer: connection, server error
    REFUSAL = "refusal"
    INVALID_REPLY = "invalid_reply"  # an answer that is no `Draft`
    SKIPPED = "skipped"  # no call made: the circuit breaker is open or `--max-calls` is spent


@dataclass(frozen=True)
class CallFailure:
    """Why an Analyst attempt has no draft; `detail` goes back to the Analyst on a retry."""

    code: CallError
    detail: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "code", CallError(self.code))
        except ValueError:
            raise ValueError(f"call failure: {self.code!r} is not a CallError") from None
        _strs(self, "call failure", "detail")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "detail": self.detail}

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        _check_keys(data, cls)
        return cls(**data)


@dataclass(frozen=True)
class Attempt:
    """One Analyst attempt. `draft` is None when it failed (`error` says why, and a skipped
    attempt made no model call); `verdict` is None until the Guard has judged it. `requests`
    counts the model requests it made: two when the Analyst read the facts with a tool."""

    n: int
    model: str
    draft: Draft | None
    error: CallFailure | None = None
    verdict: Verdict | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    requests: int = 0

    def __post_init__(self) -> None:
        what = f"attempt {self.n!r}"
        _int(self.n, 1, f"{what}: n")
        for name in ("tokens_in", "tokens_out", "latency_ms", "requests"):
            _int(getattr(self, name), 0, f"{what}: {name}")
        _strs(self, what, "model")
        if (self.draft is None) == (self.error is None):
            raise ValueError(f"{what}: exactly one of draft and error")
        for name, kind in (("draft", Draft), ("error", CallFailure), ("verdict", Verdict)):
            value = getattr(self, name)
            if value is not None and not isinstance(value, kind):
                raise ValueError(f"{what}: {name} is a {type(value).__name__}")
        if self.verdict is None:
            return
        if self.draft is None and self.verdict.passed:
            raise ValueError(f"{what}: a failed attempt cannot pass the Guard")
        claims = 0 if self.draft is None else len(self.draft.claims)
        pointed = [r.claim for r in self.verdict.reasons if r.claim is not None]
        if bad := [i for i in pointed if i >= claims]:
            raise ValueError(f"{what}: reasons point at claims {bad}, the draft has {claims}")

    @property
    def called_model(self) -> bool:
        return self.error is None or self.error.code is not CallError.SKIPPED

    def judged(self, verdict: Verdict) -> Self:
        if self.verdict is not None:
            raise ValueError(f"attempt {self.n} is already judged")
        return replace(self, verdict=verdict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "model": self.model,
            "draft": None if self.draft is None else self.draft.to_dict(),
            "error": None if self.error is None else self.error.to_dict(),
            "verdict": None if self.verdict is None else self.verdict.to_dict(),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "latency_ms": self.latency_ms,
            "requests": self.requests,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        _check_keys(data, cls)
        draft = None if data["draft"] is None else Draft.from_dict(data["draft"])
        error = None if data["error"] is None else CallFailure.from_dict(data["error"])
        verdict = None if data["verdict"] is None else Verdict.from_dict(data["verdict"])
        return cls(**(data | {"draft": draft, "error": error, "verdict": verdict}))


class _Rewriting:
    """What a rendition and a translation share: attempts at a text that passed, each judged by
    the Guard, at most `limit`, ending as passed (the last attempt passed) or as a fallback to
    the text it started from. `what` names it in errors."""

    attempts: tuple[Attempt, ...]
    outcome: RenditionOutcome
    limit: int
    what: str

    def _check_attempts(self) -> None:
        what = self.what
        _tuple(self, "attempts", Attempt, what)
        if [a.n for a in self.attempts] != list(range(1, len(self.attempts) + 1)):
            raise ValueError(f"{what}: attempts must be numbered 1, 2, ...")
        if len(self.attempts) > self.limit:
            raise ValueError(f"{what}: {len(self.attempts)} attempts, at most {self.limit}")
        if any(a.verdict is None or a.verdict.passed for a in self.attempts[:-1]):
            raise ValueError(f"{what}: every attempt but the last must be judged and rejected")
        last = self.attempts[-1].verdict if self.attempts else None
        if (last is not None and last.passed) != (self.outcome is RenditionOutcome.PASSED):
            raise ValueError(f"{what}: {self.outcome}, but the last attempt passed: {last}")
        if self.outcome is RenditionOutcome.FALLBACK and self.attempts and last is None:
            raise ValueError(f"{what}: a fallback with an attempt the Guard has not judged")

    @property
    def is_open(self) -> bool:
        return self.outcome is RenditionOutcome.PENDING

    @property
    def draft(self) -> Draft | None:
        """Its own draft that passed the Guard; None unless it passed."""
        return self.attempts[-1].draft if self.outcome is RenditionOutcome.PASSED else None

    @property
    def can_retry(self) -> bool:
        """Open, its last attempt rejected after a model call, and an attempt left."""
        last = self.attempts[-1] if self.attempts else None
        return (
            self.is_open
            and last is not None
            and last.verdict is not None
            and last.called_model
            and len(self.attempts) < self.limit
        )

    def with_attempt(self, attempt: Attempt) -> Self:
        if not self.is_open:
            raise ValueError(f"{self.what} is closed ({self.outcome})")
        return replace(self, attempts=(*self.attempts, attempt))

    def with_verdict(self, verdict: Verdict) -> Self:
        """The Guard's verdict on the last attempt; a pass ends it as passed."""
        if not self.attempts:
            raise ValueError(f"{self.what}: no attempt to judge")
        attempts = (*self.attempts[:-1], self.attempts[-1].judged(verdict))
        outcome = RenditionOutcome.PASSED if verdict.passed else RenditionOutcome.PENDING
        return replace(self, attempts=attempts, outcome=outcome)

    def fallback(self) -> Self:
        if not self.is_open:
            raise ValueError(f"{self.what} is closed ({self.outcome})")
        return replace(self, outcome=RenditionOutcome.FALLBACK)


@dataclass(frozen=True)
class Rendition(_Rewriting):
    """A narrative rewritten for one persona: the Persona Editor's attempts, each judged by the
    Guard, at most `PERSONA_ATTEMPTS`."""

    persona: Persona
    attempts: tuple[Attempt, ...] = ()
    outcome: RenditionOutcome = RenditionOutcome.PENDING
    limit = PERSONA_ATTEMPTS

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "persona", Persona(self.persona))
            object.__setattr__(self, "outcome", RenditionOutcome(self.outcome))
        except ValueError as e:
            raise ValueError(f"rendition: {e}") from None
        self._check_attempts()

    @property
    def what(self) -> str:
        return f"rendition {self.persona.value!r}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "persona": self.persona.value,
            "attempts": [a.to_dict() for a in self.attempts],
            "outcome": self.outcome.value,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        _check_keys(data, cls)
        return cls(**(data | {"attempts": _items(data["attempts"], Attempt, "rendition attempts")}))


@dataclass(frozen=True)
class Translation(_Rewriting):
    """A text a persona reads, translated into `lang`: the Translator's attempts, each judged by
    the Guard in that language against the source, at most `TRANSLATION_ATTEMPTS`. `persona`:
    whose text it is, `ANALYST` for the narrative, a `Persona` for its own rendition."""

    lang: Lang
    persona: str
    attempts: tuple[Attempt, ...] = ()
    outcome: RenditionOutcome = RenditionOutcome.PENDING
    limit = TRANSLATION_ATTEMPTS

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "lang", Lang(self.lang))
            object.__setattr__(self, "outcome", RenditionOutcome(self.outcome))
            if self.persona != ANALYST:
                Persona(self.persona)
        except ValueError as e:
            raise ValueError(f"translation: {e}") from None
        self._check_attempts()

    @property
    def what(self) -> str:
        return f"translation {self.lang.value!r} of {self.persona!r}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "lang": self.lang.value,
            "persona": self.persona,
            "attempts": [a.to_dict() for a in self.attempts],
            "outcome": self.outcome.value,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        _check_keys(data, cls)
        attempts = _items(data["attempts"], Attempt, "translation attempts")
        return cls(**(data | {"attempts": attempts}))


@dataclass(frozen=True)
class MomentCase:
    """A key moment on its way through the agents.

    `facts` are the Fact payloads the Analyst sees, JSON objects with at least a unique
    `fact_id` and a `display` string (the Moment Detector stores `facts.brief`, a Fact without its
    id lists); the Guard does not trust them and looks every cited fact id up in the stats engine
    itself. `trigger_ids` are the events of the match that make the moment (a shot and its goal
    or save, or a shot that hits the woodwork), and `display_clock` is the broadcast clock at
    `end_ms`.
    """

    run_id: str
    match_id: str
    moment_id: str
    trigger_ids: tuple[str, ...]
    period: int
    start_ms: int
    end_ms: int
    display_clock: str
    facts: tuple[dict[str, Any], ...]
    attempts: tuple[Attempt, ...] = ()
    outcome: MomentOutcome = MomentOutcome.PENDING
    renditions: tuple[Rendition, ...] = ()  # of a narrative, one per persona, in the run's order
    translations: tuple[Translation, ...] = ()  # of a narrative and the renditions that passed

    def __post_init__(self) -> None:
        what = f"moment {self.moment_id!r}"
        _strs(self, what, "run_id", "match_id", "moment_id", "display_clock")
        _tuple(self, "trigger_ids", str, what)
        _tuple(self, "facts", dict, what)
        _tuple(self, "attempts", Attempt, what)
        object.__setattr__(self, "facts", tuple(_fact(f, what) for f in self.facts))
        if len({f["fact_id"] for f in self.facts}) != len(self.facts):
            raise ValueError(f"{what}: duplicate fact ids")
        try:
            object.__setattr__(self, "outcome", MomentOutcome(self.outcome))
        except ValueError:
            raise ValueError(f"{what}: {self.outcome!r} is not an outcome") from None
        if not self.trigger_ids:
            raise ValueError(f"{what}: no trigger event")
        if len(set(self.trigger_ids)) != len(self.trigger_ids):
            raise ValueError(f"{what}: duplicate trigger ids")
        if others := [t for t in self.trigger_ids if parse_event_id(t)[0] != self.match_id]:
            raise ValueError(f"{what}: triggers {others} are not events of {self.match_id}")
        if type(self.period) is not int or self.period not in PERIODS:
            raise ValueError(f"{what}: period = {self.period!r} is not one of {PERIODS}")
        _int(self.start_ms, 0, f"{what}: start_ms")
        _int(self.end_ms, self.start_ms, f"{what}: end_ms")
        if self.end_ms > MAX_PERIOD_MS:
            raise ValueError(f"{what}: end_ms {self.end_ms} is past the longest period")
        if self.display_clock != (clock := display_clock(self.period, self.end_ms)):
            raise ValueError(f"{what}: display clock {self.display_clock!r}, at end_ms {clock}")
        if [a.n for a in self.attempts] != list(range(1, len(self.attempts) + 1)):
            raise ValueError(f"{what}: attempts must be numbered 1, 2, ...")
        if len(self.attempts) > MAX_ATTEMPTS:
            raise ValueError(f"{what}: {len(self.attempts)} attempts, at most {MAX_ATTEMPTS}")
        if any(a.verdict is None or a.verdict.passed for a in self.attempts[:-1]):
            raise ValueError(f"{what}: every attempt but the last must be judged and rejected")
        last = self.attempts[-1].verdict if self.attempts else None
        passed = last is not None and last.passed
        if passed != (self.outcome is MomentOutcome.NARRATIVE):
            raise ValueError(f"{what}: {self.outcome}, but the last attempt passed: {passed}")
        if self.outcome is MomentOutcome.STATS_ONLY and self.attempts and last is None:
            raise ValueError(f"{what}: stats-only with an attempt the Guard has not judged")
        _tuple(self, "renditions", Rendition, what)
        if self.renditions and self.outcome is not MomentOutcome.NARRATIVE:
            raise ValueError(f"{what}: renditions of a case that is no narrative ({self.outcome})")
        personas = [r.persona for r in self.renditions]
        if len(set(personas)) != len(personas):
            raise ValueError(f"{what}: two renditions for one persona")
        _tuple(self, "translations", Translation, what)
        if self.translations and (
            self.outcome is not MomentOutcome.NARRATIVE or self.pending_rendition
        ):
            raise ValueError(f"{what}: translations before its narrative and renditions are closed")
        keys = [(t.lang, t.persona) for t in self.translations]
        if len(set(keys)) != len(keys):
            raise ValueError(f"{what}: two translations of one text into one language")
        own = {ANALYST, *(r.persona.value for r in self.renditions if r.draft is not None)}
        if strays := sorted({t.persona for t in self.translations} - own):
            raise ValueError(f"{what}: translations of {strays}, whose own text did not pass")

    @property
    def is_open(self) -> bool:
        return self.outcome is MomentOutcome.PENDING

    @property
    def is_recap(self) -> bool:
        """The match's recap at full time rather than a key moment."""
        return self.moment_id == RECAP_ID

    @property
    def pending_rendition(self) -> Rendition | None:
        """The first rendition still open; the Persona Editor works on one at a time."""
        return next((r for r in self.renditions if r.is_open), None)

    def rendition(self, persona: Persona | str) -> Draft | None:
        """What the case shows a persona: its own draft that passed, else the narrative; None for
        a case that is no narrative or a rendition still open."""
        r = next((r for r in self.renditions if r.persona == Persona(persona)), None)
        if r is None or r.is_open:
            return None
        return r.draft or self.narrative

    def with_personas(self, personas: Sequence[Persona | str]) -> Self:
        """A narrative's renditions to come, one per persona, none written yet."""
        if self.outcome is not MomentOutcome.NARRATIVE or self.renditions:
            raise ValueError(f"moment {self.moment_id!r}: renditions only once, of a narrative")
        return replace(self, renditions=tuple(Rendition(Persona(p)) for p in personas))

    @property
    def pending_translation(self) -> Translation | None:
        """The first translation still open; the Translator works on one at a time."""
        return next((t for t in self.translations if t.is_open), None)

    def with_translations(self, langs: Sequence[Lang | str]) -> Self:
        """The translations to come into each of `langs`, none written yet: of the narrative and
        of each persona's own draft that passed, the texts the personas read."""
        if self.outcome is not MomentOutcome.NARRATIVE or self.pending_rendition is not None:
            raise ValueError(f"moment {self.moment_id!r}: translations only of a closed narrative")
        if self.translations:
            raise ValueError(f"moment {self.moment_id!r}: translations only once")
        own = [ANALYST, *(r.persona.value for r in self.renditions if r.draft is not None)]
        return replace(
            self,
            translations=tuple(
                Translation(Lang(lang), p) for lang in dict.fromkeys(langs) for p in own
            ),
        )

    def with_translation(self, translation: Translation) -> Self:
        """`translation` in place of the case's translation of the same text and language."""
        key = (translation.lang, translation.persona)
        if key not in [(t.lang, t.persona) for t in self.translations]:
            raise ValueError(f"moment {self.moment_id!r}: no translation {key}")
        translations = tuple(
            translation if (t.lang, t.persona) == key else t for t in self.translations
        )
        return replace(self, translations=translations)

    def source(self, translation: Translation) -> Draft:
        """The text `translation` translates: the narrative, or its persona's own draft."""
        if translation.persona == ANALYST:
            draft = self.narrative
        else:
            draft = next(
                (r.draft for r in self.renditions if r.persona.value == translation.persona), None
            )
        if draft is None:
            raise ValueError(f"moment {self.moment_id!r}: no text of {translation.persona!r}")
        return draft

    def translated_as_logged(self, persona: str, lang: Lang | str) -> Draft | None:
        """What `persona` (`ANALYST` or a `Persona`) reads in `lang` as the case holds it: the
        translation that passed of the text it reads in English (its own draft, else the
        narrative); None without one. Not judged again: the replay does that
        (`render.recap.translated`)."""
        mine = next((r for r in self.renditions if r.persona.value == persona), None)
        whose = persona if mine is not None and mine.draft is not None else ANALYST
        found = (t for t in self.translations if (t.lang, t.persona) == (Lang(lang), whose))
        return next((t.draft for t in found), None)

    def with_rendition(self, rendition: Rendition) -> Self:
        """`rendition` in place of the case's rendition for the same persona."""
        if rendition.persona not in [r.persona for r in self.renditions]:
            raise ValueError(f"moment {self.moment_id!r}: no rendition {rendition.persona}")
        renditions = tuple(
            rendition if r.persona == rendition.persona else r for r in self.renditions
        )
        return replace(self, renditions=renditions)

    @property
    def narrative(self) -> Draft | None:
        """The draft that passed the Guard; None unless the case ended as a narrative."""
        return self.attempts[-1].draft if self.outcome is MomentOutcome.NARRATIVE else None

    def with_attempt(self, attempt: Attempt) -> Self:
        if not self.is_open:
            raise ValueError(f"moment {self.moment_id!r} is closed ({self.outcome})")
        return replace(self, attempts=(*self.attempts, attempt))

    def with_verdict(self, verdict: Verdict) -> Self:
        """The Guard's verdict on the last attempt; a pass ends the case as a narrative."""
        if not self.attempts:
            raise ValueError(f"moment {self.moment_id!r}: no attempt to judge")
        attempts = (*self.attempts[:-1], self.attempts[-1].judged(verdict))
        outcome = MomentOutcome.NARRATIVE if verdict.passed else MomentOutcome.PENDING
        return replace(self, attempts=attempts, outcome=outcome)

    def stats_only(self) -> Self:
        return replace(self, outcome=MomentOutcome.STATS_ONLY)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "match_id": self.match_id,
            "moment_id": self.moment_id,
            "trigger_ids": list(self.trigger_ids),
            "period": self.period,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "display_clock": self.display_clock,
            "facts": copy.deepcopy(list(self.facts)),
            "attempts": [a.to_dict() for a in self.attempts],
            "outcome": self.outcome.value,
            "renditions": [r.to_dict() for r in self.renditions],
            "translations": [t.to_dict() for t in self.translations],
        }

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        """Also reads a case logged before renditions existed (handoff schema v2) and before
        translations existed (v3): none."""
        if isinstance(data, dict):
            data = {"renditions": [], "translations": []} | data
        _check_keys(data, cls)
        translations = _items(data["translations"], Translation, "moment translations")
        return cls(
            **(
                data
                | {
                    "attempts": _items(data["attempts"], Attempt, "moment attempts"),
                    "renditions": _items(data["renditions"], Rendition, "moment renditions"),
                    "translations": translations,
                }
            )
        )


def _check_keys(data: Any, cls: type) -> None:
    """Exactly the dataclass fields must be present."""
    if not isinstance(data, dict):
        raise ValueError(f"{cls.__name__} must be a JSON object, got {type(data).__name__}")
    expected = {f.name for f in fields(cls)}
    if missing := sorted(expected - data.keys()):
        raise ValueError(f"{cls.__name__}: missing keys: {', '.join(missing)}")
    if unknown := sorted(str(k) for k in data.keys() - expected):
        raise ValueError(f"{cls.__name__}: unknown keys: {', '.join(unknown)}")


def _items(value: Any, cls: Any, what: str) -> tuple:
    """A JSON array of objects, each read with `cls.from_dict`."""
    if not isinstance(value, list | tuple):
        raise ValueError(f"{what} must be a JSON array, got {type(value).__name__}")
    return tuple(cls.from_dict(item) for item in value)


def _fact(fact: dict[str, Any], what: str) -> dict[str, Any]:
    """A normalized copy: strict JSON (no NaN, no tuple or set, string keys) with a `fact_id`
    and a `display` string."""
    try:
        fact = json.loads(json.dumps(fact, allow_nan=False))
    except (TypeError, ValueError) as e:
        raise ValueError(f"{what}: a fact that is no strict JSON: {e}") from None
    if not all(isinstance(fact.get(key), str) for key in ("fact_id", "display")):
        raise ValueError(f"{what}: a fact needs fact_id and display strings, got {sorted(fact)}")
    return fact


def _tuple(obj: Any, name: str, kind: type, what: str) -> None:
    """Store field `name` as a tuple of `kind`: a list is converted, anything else refused."""
    value = getattr(obj, name)
    if not isinstance(value, list | tuple):
        raise ValueError(f"{what}: {name} must be a list, got {type(value).__name__}")
    if bad := [type(item).__name__ for item in value if not isinstance(item, kind)]:
        raise ValueError(f"{what}: {name} holds {', '.join(bad)}, not {kind.__name__}")
    object.__setattr__(obj, name, tuple(value))


def _strs(obj: Any, what: str, *names: str) -> None:
    for name in names:
        if not isinstance(getattr(obj, name), str):
            raise ValueError(f"{what}: {name} = {getattr(obj, name)!r} is not a string")


def _int(value: Any, low: int, what: str) -> None:
    # type() rather than isinstance(): bool is an int subclass and must not pass
    if type(value) is not int or value < low:
        raise ValueError(f"{what} = {value!r} is not an int of at least {low}")

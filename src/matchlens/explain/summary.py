"""The run summary: what a run's handoff log says, after every moment's chain is checked.

Each log line checks itself (`explain.log`); here a moment's lines must form one chain: the
Detector sends first, each line's receiver sends the next, the case keeps its identity (run,
match, moment, triggers, clock, facts), the Analyst adds one attempt and the Guard its verdict
and nothing else (and, on a narrative, the renditions to come), the Persona Editor adds one
attempt to the rendition being written and the Guard its verdict (and may close it), and one
Render line ends it, with every rendition closed. A broken chain is a bug and raises; a moment
whose chain stops before Render is a crash (the run stopped), neither a pass nor a fail. A
recap's chain (`explain.recap`) is a moment's with the Recap Writer in the Analyst's place, so
its log is summarized alike: one moment, a narrative or the fallback (`stats_only`). A
translation run's chain (`explain.translate`) starts with the Guard's handoff of a closed case to
the Translator, which adds one attempt to the translation being written, and the Guard its
verdict (and may close it), until one Render line ends it with every translation closed.

Pass rates count finished moments: first attempt = moments whose attempt 1 passed, final =
moments that end with a narrative. A moment's latency is the sum of its attempts' latencies
(the model calls and the facts tool's; the Guard takes milliseconds), p50 and p95 by nearest
rank. Cost is tokens times Anthropic's list price, which Foundry bills through the Marketplace.
The fields above are the Analyst's, of the chains that start at the Detector; `personas` has
each persona's renditions of those chains alike (pass rates over the renditions written,
latency summed per rendition), `translations` each language's translations of each persona's
text alike (`sk/analyst`, `sk/fan`), and `total_*` count every agent's attempts in the log.
"""

import dataclasses
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from matchlens.explain.log import Handoff, Role
from matchlens.explain.state import Attempt, MomentCase, MomentOutcome, RenditionOutcome

# US dollars per million tokens in, out (PROGRESS.md, M3, Foundry deployments, 20 Oct)
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "fake": (0.0, 0.0),
}


@dataclass(frozen=True)
class RunSummary:
    run_id: str | None
    match_id: str | None
    models: tuple[str, ...]  # what the attempts record as their model
    moments: int  # finished: a Render line ends their chain
    narratives: int
    stats_only: int
    crashed: tuple[str, ...]  # moment ids whose chain stops before Render
    first_attempt_passed: int
    attempts: int
    model_calls: int  # attempts that called the model
    model_requests: int  # their requests: two when the Analyst read the facts with a tool
    skipped: int
    errors: dict[str, int]  # call failures by code
    reasons: dict[str, int]  # the Guard's reasons by code, over every rejected attempt
    tokens_in: int
    tokens_out: int
    cost_usd: float | None  # None when a model has no known price
    latency_ms_p50: int | None
    latency_ms_p95: int | None
    stopped: str | None = None  # why the run stopped early
    personas: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    translations: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    total_requests: int = 0  # every agent's model requests
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float | None = 0.0

    @property
    def first_attempt_pass_rate(self) -> float | None:
        return self.first_attempt_passed / self.moments if self.moments else None

    @property
    def final_pass_rate(self) -> float | None:
        return self.narratives / self.moments if self.moments else None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self) | {
            "models": list(self.models),
            "crashed": list(self.crashed),
            "first_attempt_pass_rate": self.first_attempt_pass_rate,
            "final_pass_rate": self.final_pass_rate,
        }


_STARTS = {
    (Role.DETECTOR, Role.ANALYST),
    (Role.DETECTOR, Role.RECAP_WRITER),
    (Role.GUARD, Role.TRANSLATOR),  # a translation run: a closed case
}


def chains(handoffs: Sequence[Handoff]) -> dict[str, list[Handoff]]:
    """Each moment's lines in log order, the moments in the order they first appear; a broken
    chain raises ValueError."""
    by_moment: dict[str, list[Handoff]] = {}
    for h in handoffs:
        by_moment.setdefault(h.case.moment_id, []).append(h)
    for lines in by_moment.values():
        check_chain(lines)
    return by_moment


def check_chain(lines: Sequence[Handoff]) -> None:
    """One moment's lines form one chain from the Detector, at most to one Render line."""
    moment = lines[0].case.moment_id
    if (lines[0].sender, lines[0].receiver) not in _STARTS:
        raise ValueError(f"moment {moment!r}: its first line is {lines[0].sender} → ...")
    if lines[0].receiver is Role.TRANSLATOR and any(t.attempts for t in lines[0].case.translations):
        raise ValueError(f"moment {moment!r}: a translation run starts with a translation written")
    identity = _identity(lines[0].case)
    for before, line in pairwise(lines):
        if before.receiver is Role.RENDER:
            raise ValueError(f"moment {moment!r}: a line after the one to {Role.RENDER}")
        if line.sender is not before.receiver:
            raise ValueError(
                f"moment {moment!r}: {line.sender} sends at {line.ts}, the case was with "
                f"{before.receiver}"
            )
        if _identity(line.case) != identity:
            raise ValueError(f"moment {moment!r}: the case changed its identity at {line.ts}")
        if not _single_step(line.sender, before.case, line.case):
            raise ValueError(f"moment {moment!r}: {line.sender} at {line.ts} is no single step")


def _single_step(sender: Role, before: MomentCase, after: MomentCase) -> bool:
    """Whether `after` is `before` plus exactly what `sender` may add."""
    old, new = before.attempts, after.attempts
    if sender in (Role.ANALYST, Role.RECAP_WRITER):
        return _added(old, new) and not after.renditions and not after.translations
    same = old == new and before.outcome == after.outcome
    if sender in (Role.PERSONA_EDITOR, Role.TRANSLATOR):
        changed = _changed(before, after, translation=sender is Role.TRANSLATOR)
        return (
            same
            and changed is not None
            and changed[1].outcome == changed[0].outcome
            and _added(changed[0].attempts, changed[1].attempts)
        )
    if before.is_open:  # the Guard on the Analyst's attempt, maybe opening the renditions
        fresh = all(not r.attempts and r.is_open for r in after.renditions)
        return _judged(old, new) and not before.renditions and fresh and not after.translations
    # the Guard on a rendition's or a translation's attempt, maybe closing it
    changed = _changed(before, after, translation=before.renditions == after.renditions)
    if changed is None:
        return False
    judged = changed[1]
    # a fallback only when no retry is left: the policy, not just a closed rendition
    if (
        judged.outcome is RenditionOutcome.FALLBACK
        and dataclasses.replace(judged, outcome=RenditionOutcome.PENDING).can_retry
    ):
        return False
    return same and _judged(changed[0].attempts, judged.attempts)


def _added(old: tuple[Attempt, ...], new: tuple[Attempt, ...]) -> bool:
    return len(new) == len(old) + 1 and new[:-1] == old and new[-1].verdict is None


def _judged(old: tuple[Attempt, ...], new: tuple[Attempt, ...]) -> bool:
    return (
        len(new) == len(old) > 0
        and new[:-1] == old[:-1]
        and new[-1].verdict is not None
        and dataclasses.replace(new[-1], verdict=None) == old[-1]
    )


def _changed(before: MomentCase, after: MomentCase, *, translation: bool):
    """The one rendition (or translation) that differs, as (before, after), when the other kind
    did not change; None if not exactly one."""
    if translation:
        old, new = before.translations, after.translations
        keys = [(t.lang, t.persona) for t in old], [(t.lang, t.persona) for t in new]
        others = before.renditions == after.renditions
    else:
        old, new = before.renditions, after.renditions
        keys = [r.persona for r in old], [r.persona for r in new]
        others = before.translations == after.translations
    if keys[0] != keys[1] or not others:
        return None
    diff = [(a, b) for a, b in zip(old, new, strict=True) if a != b]
    return diff[0] if len(diff) == 1 else None


def _identity(case: MomentCase) -> dict[str, Any]:
    d = case.to_dict()
    del d["attempts"], d["outcome"], d["renditions"], d["translations"]
    return d


def summarize(handoffs: Sequence[Handoff], stopped: str | None = None) -> RunSummary:
    """The summary of one run's log; ValueError when a chain is broken or the lines are of more
    than one run or match."""
    runs = {(h.case.run_id, h.case.match_id) for h in handoffs}
    if len(runs) > 1:
        raise ValueError(f"a log of one run and match, got {sorted(runs)}")
    run_id, match_id = next(iter(runs), (None, None))
    by_moment = chains(handoffs).values()
    last = [lines[-1] for lines in by_moment]
    # a translation run's chains carry the run's drafts and renditions: not its attempts
    drafted = [lines[-1] for lines in by_moment if lines[0].receiver is not Role.TRANSLATOR]
    finished = [h.case for h in drafted if h.receiver is Role.RENDER]
    attempts = [a for h in drafted for a in h.case.attempts]
    latencies = sorted(sum(a.latency_ms for a in c.attempts) for c in finished)
    cost = _cost(attempts)
    renditions = [r for h in drafted for r in h.case.renditions]
    translations = [t for h in last for t in h.case.translations]
    written = [a for r in renditions for a in r.attempts]
    translated = [a for t in translations for a in t.attempts]
    every = attempts + written + translated
    models = tuple(sorted({a.model for a in every}))
    return RunSummary(
        run_id=run_id,
        match_id=match_id,
        models=models,
        moments=len(finished),
        narratives=sum(c.outcome is MomentOutcome.NARRATIVE for c in finished),
        stats_only=sum(c.outcome is MomentOutcome.STATS_ONLY for c in finished),
        crashed=tuple(h.case.moment_id for h in last if h.receiver is not Role.RENDER),
        first_attempt_passed=sum(c.attempts[0].verdict.passed for c in finished),
        attempts=len(attempts),
        model_calls=sum(a.called_model for a in attempts),
        model_requests=sum(a.requests for a in attempts),
        skipped=sum(not a.called_model for a in attempts),
        errors=_tally(a.error.code.value for a in attempts if a.error),
        reasons=_tally(r.code.value for a in attempts if a.verdict for r in a.verdict.reasons),
        tokens_in=sum(a.tokens_in for a in attempts),
        tokens_out=sum(a.tokens_out for a in attempts),
        cost_usd=None if cost is None else round(cost, 6),
        latency_ms_p50=_rank(latencies, 0.50),
        latency_ms_p95=_rank(latencies, 0.95),
        stopped=stopped,
        personas={
            p.value: _persona(rs)
            for p in dict.fromkeys(r.persona for r in renditions)
            if (rs := [r for r in renditions if r.persona == p])
        },
        translations={
            f"{lang.value}/{persona}": _persona(ts, "translations")
            for lang, persona in dict.fromkeys((t.lang, t.persona) for t in translations)
            if (ts := [t for t in translations if (t.lang, t.persona) == (lang, persona)])
        },
        total_requests=sum(a.requests for a in every),
        total_tokens_in=sum(a.tokens_in for a in every),
        total_tokens_out=sum(a.tokens_out for a in every),
        total_cost_usd=None if (c := _cost(every)) is None else round(c, 6),
    )


def _cost(attempts: Sequence[Attempt]) -> float | None:
    """Tokens times list price; None when a model has no known price."""
    if not all(a.model in PRICES for a in attempts):
        return None
    return sum(
        (a.tokens_in * PRICES[a.model][0] + a.tokens_out * PRICES[a.model][1]) / 1e6
        for a in attempts
    )


def _persona(renditions, noun: str = "renditions") -> dict[str, Any]:
    """One persona's renditions (or translations: `noun`), counted like the Analyst's moments;
    open ones are a crash."""
    closed = [r for r in renditions if not r.is_open]
    attempts = [a for r in renditions for a in r.attempts]
    latencies = sorted(sum(a.latency_ms for a in r.attempts) for r in closed)
    written = [r for r in closed if r.attempts]
    cost = _cost(attempts)
    return {
        noun: len(closed),
        "passed": sum(r.outcome is RenditionOutcome.PASSED for r in closed),
        "fallback": sum(r.outcome is RenditionOutcome.FALLBACK for r in closed),
        "open": len(renditions) - len(closed),
        "first_attempt_passed": sum(r.attempts[0].verdict.passed for r in written),
        "attempts": len(attempts),
        "model_calls": sum(a.called_model for a in attempts),
        "model_requests": sum(a.requests for a in attempts),
        "skipped": sum(not a.called_model for a in attempts),
        "errors": _tally(a.error.code.value for a in attempts if a.error),
        "reasons": _tally(r.code.value for a in attempts if a.verdict for r in a.verdict.reasons),
        "tokens_in": sum(a.tokens_in for a in attempts),
        "tokens_out": sum(a.tokens_out for a in attempts),
        "cost_usd": None if cost is None else round(cost, 6),
        "latency_ms_p50": _rank(latencies, 0.50),
        "latency_ms_p95": _rank(latencies, 0.95),
    }


def _tally(codes: Iterable[str]) -> dict[str, int]:
    """How often each code occurs, the codes in order."""
    return dict(sorted(Counter(codes).items()))


def _rank(values: Sequence[int], q: float) -> int | None:
    """The nearest-rank percentile of sorted `values`."""
    return values[max(1, math.ceil(q * len(values))) - 1] if values else None

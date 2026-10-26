"""The handoff log: one JSON line each time an agent passes a `MomentCase` on, with the whole case.

The Guard pass rate and the run summary are computed from this log, so it records what each agent
actually received, not a summary of it. A `Handoff` checks its route and that the case is in the
phase the route expects, on writing and on reading: no line shows an unjudged draft leaving or a
route the graph lacks. Each line checks itself only; whether a moment's lines form one unbroken
chain is for the run summary to check. Timestamps are UTC (ISO 8601, offset +00:00); every line
carries the schema version `v`; a reader takes v2 (before renditions), v3 (before translations)
and v4. A match's recap (`explain.recap`) is a case like a moment's, with its own writer: only
the Recap Writer drafts it, and only the Analyst drafts a key moment. A translation run
(`explain.translate`) logs a closed case's way to the Translator and back: its first line is the
Guard's handoff of a case with translations to write.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

from matchlens.explain.state import MAX_ATTEMPTS, PERSONA_ATTEMPTS, MomentCase

# 2: an attempt records its model requests; 3: a case has renditions; 4: and translations
SCHEMA_VERSION = 4
READABLE_VERSIONS = (2, 3, 4)  # a v2 case has no renditions, a v3 case no translations
_KEYS = {"v", "ts", "from", "to", "moment_id", "attempt", "state"}


class Role(StrEnum):
    DETECTOR = "moment_detector"
    ANALYST = "analyst"
    GUARD = "guard"
    PERSONA_EDITOR = "persona_editor"
    RECAP_WRITER = "recap_writer"
    TRANSLATOR = "translator"
    RENDER = "render"  # the cue leaves the Explain stage


def _fresh(case: MomentCase) -> bool:
    return case.is_open and not case.attempts


def _drafted(case: MomentCase) -> bool:
    return bool(case.attempts) and case.attempts[-1].verdict is None


def _retry(case: MomentCase) -> bool:
    return case.is_open and 0 < len(case.attempts) < MAX_ATTEMPTS and not _drafted(case)


def _closed(case: MomentCase) -> bool:
    return not case.is_open and case.pending_rendition is None and case.pending_translation is None


def _persona_due(case: MomentCase) -> bool:
    r = case.pending_rendition
    return not case.is_open and r is not None and (not r.attempts or r.can_retry)


def _rendered(case: MomentCase) -> bool:
    r = case.pending_rendition
    return (
        not case.is_open
        and r is not None
        and bool(r.attempts)
        and len(r.attempts) <= PERSONA_ATTEMPTS
        and r.attempts[-1].verdict is None
    )


def _translation_due(case: MomentCase) -> bool:
    t = case.pending_translation
    return (
        not case.is_open
        and case.pending_rendition is None
        and t is not None
        and (not t.attempts or t.can_retry)
    )


def _translated(case: MomentCase) -> bool:
    t = case.pending_translation
    return (
        not case.is_open
        and case.pending_rendition is None
        and t is not None
        and bool(t.attempts)
        and t.attempts[-1].verdict is None
    )


def _moment(phase: Callable[[MomentCase], bool]) -> Callable[[MomentCase], bool]:
    return lambda case: not case.is_recap and phase(case)


def _recap(phase: Callable[[MomentCase], bool]) -> Callable[[MomentCase], bool]:
    return lambda case: case.is_recap and phase(case)


# the routes and the phase a case must be in to take them; the Guard is the only way out
TRANSITIONS: dict[tuple[Role, Role], Callable[[MomentCase], bool]] = {
    (Role.DETECTOR, Role.ANALYST): _moment(_fresh),  # no attempt yet
    (Role.ANALYST, Role.GUARD): _moment(_drafted),  # the last attempt waits for its verdict
    (Role.GUARD, Role.ANALYST): _moment(_retry),  # rejected, and a retry is left
    (Role.DETECTOR, Role.RECAP_WRITER): _recap(_fresh),  # at full time: the match's recap
    (Role.RECAP_WRITER, Role.GUARD): _recap(_drafted),
    (Role.GUARD, Role.RECAP_WRITER): _recap(_retry),
    (Role.GUARD, Role.PERSONA_EDITOR): _persona_due,  # a rendition to write, or to write again
    (Role.PERSONA_EDITOR, Role.GUARD): _rendered,  # a rendition's attempt waits for its verdict
    (Role.GUARD, Role.TRANSLATOR): _translation_due,  # a translation to write, or to write again
    (Role.TRANSLATOR, Role.GUARD): _translated,  # a translation's attempt waits for its verdict
    (
        Role.GUARD,
        Role.RENDER,
    ): _closed,  # a narrative, its renditions and translations, or stats-only
}


@dataclass(frozen=True)
class Handoff:
    ts: str
    sender: Role
    receiver: Role
    case: MomentCase

    def __post_init__(self) -> None:
        try:
            sender, receiver = Role(self.sender), Role(self.receiver)
        except ValueError:
            raise ValueError(f"no handoff from {self.sender!r} to {self.receiver!r}") from None
        object.__setattr__(self, "sender", sender)
        object.__setattr__(self, "receiver", receiver)
        if not isinstance(self.case, MomentCase):
            raise ValueError(f"handoff: the case is a {type(self.case).__name__}")
        _check_ts(self.ts)
        allowed = TRANSITIONS.get((sender, receiver))
        if allowed is None:
            raise ValueError(f"no handoff from {sender} to {receiver}")
        if not allowed(self.case):
            raise ValueError(
                f"moment {self.case.moment_id!r} cannot go from {sender} to {receiver} with "
                f"{len(self.case.attempts)} attempts and outcome {self.case.outcome}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": SCHEMA_VERSION,
            "ts": self.ts,
            "from": self.sender.value,
            "to": self.receiver.value,
            "moment_id": self.case.moment_id,
            "attempt": len(self.case.attempts),
            "state": self.case.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        if not isinstance(data, dict) or data.keys() != _KEYS:
            keys = sorted(data) if isinstance(data, dict) else type(data).__name__
            raise ValueError(f"a handoff line needs exactly {sorted(_KEYS)}, got {keys}")
        if data["v"] not in READABLE_VERSIONS or type(data["v"]) is not int:
            raise ValueError(
                f"handoff schema v{data['v']!r}, this reader knows {READABLE_VERSIONS}"
            )
        for v, key in ((3, "renditions"), (4, "translations")):
            if isinstance(data["state"], dict) and (data["v"] >= v) != (key in data["state"]):
                raise ValueError(
                    f"handoff at {data['ts']}: a v{data['v']} case "
                    + (f"without {key}" if data["v"] >= v else f"with {key}")
                )
        case = MomentCase.from_dict(data["state"])
        if type(data["attempt"]) is not int or (data["moment_id"], data["attempt"]) != (
            case.moment_id,
            len(case.attempts),
        ):
            raise ValueError(
                f"handoff at {data['ts']}: moment_id or attempt does not match its state"
            )
        return cls(data["ts"], data["from"], data["to"], case)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _check_ts(ts: Any) -> None:
    try:
        utc = datetime.fromisoformat(ts).utcoffset() == timedelta(0)
    except (TypeError, ValueError):
        utc = False
    if not utc:
        raise ValueError(f"handoff: ts = {ts!r} is no ISO 8601 UTC time with its offset")


def _no_constant(name: str) -> None:
    raise ValueError(f"{name} is not strict JSON")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if dupes := sorted({k for k in keys if keys.count(k) > 1}):
        raise ValueError(f"duplicate keys: {', '.join(dupes)}")
    return dict(pairs)


class HandoffLog:
    """Appends handoffs to a JSONL file; the directory is created on the first record."""

    def __init__(self, path: Path, clock: Callable[[], str] = _utc_now) -> None:
        self.path = path
        self._clock = clock

    def record(self, sender: Role, receiver: Role, case: MomentCase) -> Handoff:
        """Check the handoff, then append it; a refused handoff writes nothing."""
        handoff = Handoff(self._clock(), sender, receiver, case)
        # strict JSON (no NaN), ASCII: a raw U+0085 or U+2028 would split the line for some readers
        line = json.dumps(handoff.to_dict(), allow_nan=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)
        return handoff


def read_handoffs(path: Path) -> list[Handoff]:
    """Every handoff of a log, in order; blank lines are skipped. As strict as writing: no NaN,
    no duplicate keys; an error names its line."""
    handoffs = []
    with path.open("rb") as f:  # lines end at b"\n" only; each is decoded on its own
        for number, raw in enumerate(f, 1):
            try:
                line = raw.decode("utf-8")
                if not line.strip():
                    continue
                data = json.loads(line, parse_constant=_no_constant, object_pairs_hook=_unique_keys)
                handoffs.append(Handoff.from_dict(data))
            except ValueError as e:  # UnicodeDecodeError and JSONDecodeError are ValueErrors
                raise ValueError(f"{path}:{number}: {e}") from None
    return handoffs

"""The recap at full time: the studio's summary of the match, on the overlay and at its endpoint.

The recap is the one a run's Recap Writer wrote (`explain.recap`, the run's `recap.jsonl`),
replayed and judged by the Guard again against the whole match's facts, or else the
deterministic recap made of those facts (`fallback_recap`), exactly as the workflow lets them
out: a rejected text never shows. The fan reads the Persona Editor's rendition of a recap the
Guard passes, if it passes again on its own, else what the analyst reads. No model is called
here. The first line says who wrote it: "Recap" (the Recap Writer), "Full time in facts" (the
engine), "Fan recap" (the Persona Editor).

In each language of `Lang` a persona reads the run's translation of the text it reads in English,
if the Guard passes it again in that language and against its source, else that English text
(then the recap holds no translation for it);
the deterministic recap is written in the language's own words (`fulltime.RECAP_WORDS`). The
first line says it in that language: "Zhrnutie", "Koniec zápasu vo faktoch", "Zhrnutie pre
fanúšika". A translation run closes a closed case again with its translations (`closing`).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace

from matchlens.explain.fulltime import fallback_recap, recap_case
from matchlens.explain.guard import Evidence, check, recap_evidence
from matchlens.explain.log import Handoff, Role
from matchlens.explain.state import ANALYST, Draft, Lang, MomentCase, Persona
from matchlens.facts import Fact, Time
from matchlens.match import Match
from matchlens.render.cues import TTL_MS, Cue, CueKind, CueRendition

WRITTEN, FACTS_ONLY, FAN_RECAP = "Recap", "Full time in facts", "Fan recap"
LABELS = {
    Lang.SK: {
        WRITTEN: "Zhrnutie",
        FACTS_ONLY: "Koniec zápasu vo faktoch",
        FAN_RECAP: "Zhrnutie pre fanúšika",
    }
}
SOURCES = {WRITTEN: "recap_writer", FACTS_ONLY: "engine", FAN_RECAP: "persona_editor"}
SOURCES |= {
    words[label]: "engine" if label == FACTS_ONLY else "translator"
    for words in LABELS.values()
    for label in words
}


@dataclass(frozen=True)
class MatchRecap:
    """What each persona reads at full time: a label (who wrote it) and the draft, its claims
    with their evidence."""

    match_id: str
    due: Time
    display_clock: str
    event_ids: tuple[str, ...]  # the final whistle and every goal
    texts: dict[str, tuple[str, Draft]]  # by persona, the analyst first
    translations: dict[str, dict[str, tuple[str, Draft]]] = field(default_factory=dict)  # by lang

    def cue(self) -> Cue:
        """The `recap` cue: due at the final whistle, the analyst's lines first."""
        renditions = tuple(
            CueRendition(p, (label, draft.text), _cited(draft), self.event_ids)
            for p, (label, draft) in self.texts.items()
            if p != ANALYST
        )
        translations = tuple(
            CueRendition(p, (label, draft.text), _cited(draft), self.event_ids, lang)
            for lang, texts in self.translations.items()
            for p, (label, draft) in texts.items()
        )
        label, draft = self.texts[ANALYST]
        return Cue(
            f"{self.match_id}/cue/{CueKind.RECAP.value}/{self.event_ids[0]}",
            self.match_id,
            self.due,
            CueKind.RECAP,
            (label, draft.text),
            _cited(draft),
            event_ids=self.event_ids,
            ttl_ms=TTL_MS[CueKind.RECAP],
            renditions=renditions,
            translations=translations,
        )

    def to_dict(self) -> dict:
        """The studio output, plain JSON: per persona who wrote it, the text and its claims; the
        same per language under `translations`, for the personas whose text there is a
        translation or the engine's (a client falls back to `personas` for the others)."""

        def personas(texts: dict[str, tuple[str, Draft]]) -> dict:
            return {
                p: {
                    "label": label,
                    "source": SOURCES[label],
                    "text": draft.text,
                    "claims": [c.to_dict() for c in draft.claims],
                    "fact_ids": list(_cited(draft)),
                    "event_ids": list(self.event_ids),
                }
                for p, (label, draft) in texts.items()
            }

        return {
            "match_id": self.match_id,
            "due": list(self.due),
            "display_clock": self.display_clock,
            "personas": personas(self.texts),
            "translations": {lang: personas(t) for lang, t in self.translations.items()},
        }


def match_recap(
    match: Match, handoffs: Iterable[Handoff] = (), whole: Sequence[Fact] | None = None
) -> MatchRecap:
    """The recap of `match` from a run's log (`read_handoffs` of its `recap.jsonl`; a log's
    moment lines are left alone), judged again, else the deterministic one. `whole`: the
    match's `match_facts`, if already computed. ValueError if the log is of another match,
    closes the recap twice or holds a recap that is not of this match (triggers, clock) or whose
    facts are not the engine's."""
    meta = match.meta
    logged: MomentCase | None = None
    for h in handoffs:
        if h.case.match_id != meta.match_id:
            raise ValueError(f"a handoff of {h.case.match_id} in the log of {meta.match_id}")
        if h.case.is_recap and (h.sender, h.receiver) == (Role.GUARD, Role.RENDER):
            logged = closing(logged, h.case)
    case = recap_case(match, "replay", whole)
    if logged is not None:
        if _identity(logged) != _identity(case):
            raise ValueError(f"the recap of the log is not one of {meta.match_id}")
        recap_evidence(match, logged, whole)  # its facts, one by one, the engine's: else ValueError
    evidence = recap_evidence(match, case, whole)
    facts_only = fallback_recap(match, case, evidence)
    if not (verdict := check(facts_only, case, evidence)).passed:  # by construction; a bug else
        codes = ", ".join(r.code for r in verdict.reasons)
        raise RuntimeError(f"the deterministic recap of {meta.match_id} fails the Guard: {codes}")
    texts = {ANALYST: (FACTS_ONLY, facts_only)}
    narrative = None if logged is None else logged.narrative
    if narrative is not None and check(narrative, logged, evidence).passed:
        texts[ANALYST] = (WRITTEN, narrative)
    for persona in Persona:
        own = None
        if logged is not None and texts[ANALYST][0] == WRITTEN:  # a rendition only of a recap
            mine = [r.draft for r in logged.renditions if r.persona is persona and r.draft]
            own = next((d for d in mine if check(d, logged, evidence).passed), None)
        texts[persona.value] = (FAN_RECAP, own) if own is not None else texts[ANALYST]
    translations = {}
    for lang in Lang:
        words = LABELS[lang]
        if texts[ANALYST][0] == WRITTEN:
            mine = translated(logged, ANALYST, lang, evidence)
            there = {ANALYST: (words[WRITTEN], mine) if mine else texts[ANALYST]}
        else:
            facts_only = fallback_recap(match, case, evidence, lang)
            if not (verdict := check(facts_only, case, evidence, lang)).passed:  # a bug else
                codes = ", ".join(r.code for r in verdict.reasons)
                raise RuntimeError(f"the {lang} recap of {meta.match_id} fails the Guard: {codes}")
            there = {ANALYST: (words[FACTS_ONLY], facts_only)}
        for persona in Persona:
            label = texts[persona.value][0]
            mine = translated(logged, persona.value, lang, evidence) if label == FAN_RECAP else None
            if mine is not None:
                there[persona.value] = (words[FAN_RECAP], mine)
            else:  # its English text, or the analyst's in this language
                there[persona.value] = (
                    texts[persona.value] if label == FAN_RECAP else there[ANALYST]
                )
        # the English texts that stand in are no translations: `Cue.translated` falls back
        translations[lang.value] = {p: t for p, t in there.items() if t[0] in words.values()}
    return MatchRecap(
        meta.match_id,
        (case.period, case.end_ms),
        case.display_clock,
        case.trigger_ids,
        texts,
        translations,
    )


def closed_cases(handoffs: Iterable[Handoff]) -> dict[str, MomentCase]:
    """Each case a log's Guard → render lines close, by moment id, translation runs merged
    (`closing`)."""
    closed: dict[str, MomentCase] = {}
    for h in handoffs:
        if (h.sender, h.receiver) == (Role.GUARD, Role.RENDER):
            closed[h.case.moment_id] = closing(closed.get(h.case.moment_id), h.case)
    return closed


def closing(logged: MomentCase | None, case: MomentCase) -> MomentCase:
    """The case a Guard → render line of a log closes, given the one an earlier line closed:
    a translation run (`explain.translator`) closes a closed case again, the same case with its
    translations into languages it had none in. Anything else closes a case twice: ValueError."""
    if logged is None:
        return case
    langs = {t.lang for t in logged.translations}
    if (
        not case.translations
        or any(t.lang in langs for t in case.translations)
        or replace(case, translations=()) != replace(logged, translations=())
    ):
        raise ValueError(f"moment {case.moment_id!r} is closed twice in the log")
    return replace(logged, translations=(*logged.translations, *case.translations))


def translated(
    logged: MomentCase | None, persona: str, lang: Lang, evidence: Evidence
) -> Draft | None:
    """The run's translation into `lang` of `persona`'s own text (`ANALYST`: the narrative), if
    the Guard passes it again now, in that language and against its source."""
    for t in () if logged is None else logged.translations:
        if (t.lang, t.persona) == (lang, persona) and t.draft is not None:
            source = logged.source(t)
            return t.draft if check(t.draft, logged, evidence, lang, source).passed else None
    return None


def _identity(case: MomentCase) -> tuple:
    return case.trigger_ids, case.period, case.end_ms


def _cited(draft: Draft) -> tuple[str, ...]:
    return tuple(dict.fromkeys(f for c in draft.claims for f in c.fact_ids))

"""Moment cues: the Explain stage's key moments on the overlay, one card each.

The Moment Detector finds the moments (a goal, a saved shot, a shot off the woodwork); a moment's
cue is due when it ends. Its text is the narrative that passed the Guard in a finished run's
handoff log, replayed, or else the stats-only cue made of the engine's facts, exactly as the
Explain workflow lets them out. A logged narrative is judged by the Guard again against the
engine: one it refuses now shows as stats-only, so a rejected text never reaches the page. The
first line says which it is: "Analyst" for a narrative, "Key moment" for the facts alone.

The fan's rendition is the Persona Editor's draft that passed in the run ("Fan view"), judged by
the Guard again on its own; without one, with one the Guard refuses now, or with a narrative it
refuses now (a rendition exists only of a narrative), the fan reads the analyst's lines, as the
workflow lets the narrative stand in.

In each language of `Lang` a persona reads the run's translation of the text it reads in English
(`render.recap.translated`: judged again in that language and against its source), else that
English text, which the cue then holds no translation for; a stats-only cue is written in the
language's own words. The first line says it
in that language ("Analytik", "Kľúčový moment", "Pre fanúšika").

No model is called here: a run happens once (`matchlens explain`), its log is replayed as often
as the match is. The re-check makes a hand-edited log no worse than a model's reply, and no
better: the Guard's known limits hold here too (a capitalized word that starts a sentence is
checked only against the league's other names).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from matchlens.explain.detector import detect
from matchlens.explain.guard import Evidence, check, moment_evidence, stats_only_draft
from matchlens.explain.log import Handoff, Role
from matchlens.explain.state import ANALYST, Draft, Lang, MomentCase, Persona
from matchlens.facts import Fact, match_facts
from matchlens.league import load_league
from matchlens.match import Match
from matchlens.render.cues import TTL_MS, Cue, CueKind, CueRendition, cue_timeline, ordered
from matchlens.render.recap import MatchRecap, closing, match_recap, translated

NARRATIVE, STATS_ONLY, FAN_VIEW = "Analyst", "Key moment", "Fan view"
LABELS = {Lang.SK: {NARRATIVE: "Analytik", STATS_ONLY: "Kľúčový moment", FAN_VIEW: "Pre fanúšika"}}


def moment_cues(match: Match, handoffs: Iterable[Handoff] = ()) -> list[Cue]:
    """A `moment` cue for every key moment of `match`, in the order they end. `handoffs`: a run's
    log of this match (`read_handoffs`); its Guard → render lines give the narratives. ValueError
    if the log is of another match, names a moment the Detector does not find or closes one twice
    (but for a translation run's close, `render.recap.closing`), or if a logged narrative's facts
    are not the engine's."""
    meta = match.meta
    closed: dict[str, MomentCase] = {}
    for h in handoffs:
        if h.case.match_id != meta.match_id:
            raise ValueError(f"a handoff of {h.case.match_id} in the log of {meta.match_id}")
        if (h.sender, h.receiver) == (Role.GUARD, Role.RENDER):
            closed[h.case.moment_id] = closing(closed.get(h.case.moment_id), h.case)
    moments = detect(match, run_id="replay")
    found = {c.moment_id: c for c in moments}
    for moment_id, case in closed.items():
        mine = found.get(moment_id)
        if mine is None or (case.trigger_ids, case.period, case.end_ms) != (
            mine.trigger_ids,
            mine.period,
            mine.end_ms,
        ):
            raise ValueError(f"moment {moment_id!r} of the log is not one of {meta.match_id}")
    clubs = {c.id: c for c in load_league().clubs}
    shots = {e.event_id: e for e in match.events}
    cues = []
    for case in moments:
        logged = closed.get(case.moment_id)
        narrated = logged is not None and logged.narrative is not None  # only it has renditions
        evidence = moment_evidence(match, logged) if narrated else None
        label, draft = _text(match, logged, evidence, case)
        shot = shots[case.trigger_ids[0]]
        club = clubs[shot.team].short_name
        lines, fact_ids = (f"{label} · {club}", draft.text), _cited(draft)
        fan = _fan(logged, evidence) if label == NARRATIVE else None  # as in the workflow
        fan_lines, fan_ids = (lines, fact_ids) if fan is None else _fan_lines(fan, club)
        translations = []
        for lang in Lang:
            words = LABELS[lang]
            if label == NARRATIVE:
                mine = translated(logged, ANALYST, lang, evidence)
                there = None if mine is None else _lines(words[NARRATIVE], mine, club)
            else:
                facts_only = stats_only_draft(case, moment_evidence(match, case), lang)
                there = _lines(words[STATS_ONLY], facts_only, club)
            fan_there = there
            if fan is not None:
                mine = translated(logged, Persona.FAN.value, lang, evidence)
                fan_there = None if mine is None else _lines(words[FAN_VIEW], mine, club)
            for persona, text in ((ANALYST, there), (Persona.FAN.value, fan_there)):
                if text is not None:  # else the English text, as `Cue.translated` falls back
                    translations.append(CueRendition(persona, *text, case.trigger_ids, lang))
        cues.append(
            Cue(
                f"{meta.match_id}/cue/{CueKind.MOMENT.value}/{case.moment_id}",
                meta.match_id,
                (case.period, case.end_ms),
                CueKind.MOMENT,
                lines,
                fact_ids,
                team=shot.team,
                event_ids=case.trigger_ids,
                ttl_ms=TTL_MS[CueKind.MOMENT],
                anchor=(shot.start.x, shot.start.y),
                renditions=(CueRendition(Persona.FAN.value, fan_lines, fan_ids, case.trigger_ids),),
                translations=tuple(translations),
            )
        )
    return cues


def _text(
    match: Match, logged: MomentCase | None, evidence: Evidence | None, case: MomentCase
) -> tuple[str, Draft]:
    """The narrative of `logged` if the Guard passes it again now, else the stats-only cue."""
    narrative = None if logged is None else logged.narrative
    if narrative is not None and check(narrative, logged, evidence).passed:
        return NARRATIVE, narrative
    return STATS_ONLY, stats_only_draft(case, moment_evidence(match, case))


def _fan(logged: MomentCase | None, evidence: Evidence | None) -> Draft | None:
    """The fan's own draft that passed in the run, if the Guard passes it again now."""
    if logged is None:
        return None
    own = [r.draft for r in logged.renditions if r.persona is Persona.FAN and r.draft is not None]
    return next((d for d in own if check(d, logged, evidence).passed), None)


def _fan_lines(draft: Draft, club: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return _lines(FAN_VIEW, draft, club)


def _lines(label: str, draft: Draft, club: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """A moment card's lines (who wrote it, the club; the text) and the facts they cite."""
    return (f"{label} · {club}", draft.text), _cited(draft)


def _cited(draft: Draft) -> tuple[str, ...]:
    return tuple(dict.fromkeys(f for c in draft.claims for f in c.fact_ids))


@dataclass(frozen=True)
class Overlay:
    """What the page shows of a match: every cue, and the recap they include (None when the
    cues were given rather than computed)."""

    cues: list[Cue]
    recap: MatchRecap | None = None


def match_overlay(
    match: Match, handoffs: Iterable[Handoff] = (), whole: Sequence[Fact] | None = None
) -> Overlay:
    """Every cue the page shows: the facts' cues (`cue_timeline`), the moments' and the recap at
    full time; `handoffs`: a run's log, its moments' and its recap's lines."""
    handoffs = list(handoffs)
    whole = match_facts(match) if whole is None else whole
    recap = match_recap(match, handoffs, whole)
    moments = moment_cues(match, [h for h in handoffs if not h.case.is_recap])
    return Overlay(ordered([*cue_timeline(match, whole), *moments, recap.cue()]), recap)


def match_cues(
    match: Match, handoffs: Iterable[Handoff] = (), whole: Sequence[Fact] | None = None
) -> list[Cue]:
    """Every cue the page shows (`match_overlay`)."""
    return match_overlay(match, handoffs, whole).cues

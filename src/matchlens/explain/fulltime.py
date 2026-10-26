"""The recap's case, facts and deterministic text: what the Recap Writer (`explain.recap`), the
Persona Editor and the replay (`render.recap`) share. No agent and no Agent Framework here, so
the page's commands do not load it.

The recap is a `MomentCase` with the id `RECAP_ID` at the final whistle: its triggers are the
final whistle and every goal, its facts the club and match facts of the whole match a recap is
offered (`OFFERED`) and, of each goal's instant, its minute, the score it made and its reading.
"""

from collections.abc import Sequence
from functools import cache

from matchlens.events import EventType, display_clock
from matchlens.explain.guard import RECAP_MAX_TEXT, Evidence, goal_facts
from matchlens.explain.state import RECAP_ID, Claim, Draft, Lang, MomentCase
from matchlens.facts import Fact, brief, match_facts
from matchlens.league import load_league
from matchlens.match import Match
from matchlens.stats.readings import PHRASES

# the whole match's facts a recap is offered, of each club or the match, never a player's
OFFERED = (
    "score",
    "goals",
    "score_reading",
    "possession",
    "possession_reading",
    "pass_completion",
    "momentum",
    "momentum_reading",
    "chaos",
    "chaos_reading",
    "pressing_per_minute",
)
# the deterministic recap's sentence for each flow-of-play reading (`chaos_reading` codes)
FLOW = {
    "end_to_end": "The play was {}",
    "patient": "The play was {}",
    "steady": "The play kept {}",
}
# its words in each language: the score, the scorers (one, more), a club's share, the flow of play
RECAP_WORDS = {
    "en": {
        "score": "{home} {score} {away} at full time",
        "scorer": "{name} at {minute}",
        "scored": ("Goals by {}", "Goals by {}"),
        "and": "and",
        "possession": "Possession",
        "pass_completion": "Pass completion",
        "share": "{label} was {h} for {home} and {a} for {away}",
        "flow": FLOW,
    },
    Lang.SK: {
        "score": "Konečný výsledok {home} {score} {away}",
        "scorer": "{name} v {minute}",
        "scored": ("Skóroval {}", "Skórovali {}"),
        "and": "a",
        "possession": "Držanie lopty",
        "pass_completion": "Úspešnosť prihrávok",
        "share": "{label} {home} {h}, {away} {a}",
        "flow": {
            "end_to_end": "Celkovo to bola {}",
            "patient": "Celkovo to bola {}",
            "steady": "Celkovo to bolo {}",
        },
    },
}


def final_score_id(match_id: str) -> str:
    """The id of the whole match's score: the one a recap must state."""
    return f"{match_id}/score/match/all"


def recap_case(match: Match, run_id: str, whole: Sequence[Fact] | None = None) -> MomentCase:
    """The recap of `match` at its final whistle, with no attempt yet: its triggers are the
    final whistle and every goal, its facts the ones a recap is offered (`brief`). `whole`: the
    match's `match_facts`, if already computed."""
    meta = match.meta
    whole = match_facts(match) if whole is None else whole
    ends = [e for e in match.events if e.type is EventType.PERIOD_END]
    if not ends:
        raise ValueError(f"{meta.match_id} has no final whistle")
    end = ends[-1]
    goals = [e for e in match.events if e.type is EventType.GOAL]
    offered = sorted(
        (
            f
            for f in whole
            if f.name in OFFERED and f.player is None and f.fact_id.split("/")[2] == "match"
        ),
        key=lambda f: (OFFERED.index(f.name), f.fact_id),
    )
    for goal in goals:
        at = (goal.period, goal.clock_ms)
        offered += goal_facts(match, at)
        offered += [f for f in whole if f.name == "goal_reading" and f.end == at]
    return MomentCase(
        run_id=run_id,
        match_id=meta.match_id,
        moment_id=RECAP_ID,
        trigger_ids=(end.event_id, *(g.event_id for g in goals)),
        period=end.period,
        start_ms=0,
        end_ms=end.clock_ms,
        display_clock=display_clock(end.period, end.clock_ms),
        facts=tuple(brief(f) for f in dict((f.fact_id, f) for f in offered).values()),
    )


def recap_fact_lines(case: MomentCase, match: Match, facts=None) -> list[str]:
    """The recap's facts (`facts`, else the case's) as a prompt lists them: fact_id | write as |
    what it counts | when, the whole match or a goal's instant. A minute is written in one form
    (5'), a unit after its number."""
    clubs = _clubs()
    goals = {
        f"{e.period}-{e.clock_ms}": e.event_id for e in match.events if e.type is EventType.GOAL
    }
    lines = []
    for f in case.facts if facts is None else facts:
        kind, _, at = f["fact_id"].split("/")[2].partition("-")
        when = "the whole match"
        if kind in ("at", "to") and (goal := goals.get(at)):
            when = f"when goal {goal} was scored, not at full time"
        unit = f.get("unit") or ""
        written = f["display"] if not unit or unit in f["display"] else f"{f['display']} {unit}"
        name = str(f.get("name", "")).replace("_", " ")
        lines.append(
            f"- {f['fact_id']} | {written} | {name} of {clubs.get(f.get('team'), 'the match')} "
            f"| {when}"
        )
    return lines


def fallback_recap(match: Match, case: MomentCase, evidence: Evidence, lang: str = "en") -> Draft:
    """The recap made of the engine's facts alone, one claim a sentence: the score, the scorers
    with their minutes, possession, pass completion and the flow of play, in this order up to
    the first that does not fit into `RECAP_MAX_TEXT` characters (the score always does). In
    the words of `lang` (`RECAP_WORDS`), a reading as its phrase there."""
    words = RECAP_WORDS[lang]
    meta, facts = match.meta, evidence.facts
    clubs = _clubs()
    home, away = clubs[meta.home], clubs[meta.away]
    names = {p.id: p.name for c in load_league().clubs for p in c.players}
    end, *goals = case.trigger_ids
    events = {e.event_id: e for e in match.events}
    mid = meta.match_id
    parts: list[tuple[str, list[str], tuple[str, ...]]] = []
    if (score := facts.get(final_score_id(mid))) is not None:
        text = words["score"].format(home=home, score=score.display, away=away)
        parts.append((text, [score.fact_id], (end,)))
    scored = []
    for goal_id in goals:
        goal = events[goal_id]
        minute = facts.get(f"{mid}/minute/at-{goal.period}-{goal.clock_ms}/all")
        if minute is not None:
            scorer = words["scorer"].format(name=names[goal.player], minute=minute.display)
            scored.append((scorer, minute.fact_id, goal_id))
    if scored:
        listed = ", ".join(s for s, _, _ in scored[:-1])
        text = f"{listed} {words['and']} {scored[-1][0]}" if listed else scored[-1][0]
        sentence = words["scored"][len(scored) > 1].format(text)
        parts.append((sentence, [f for _, f, _ in scored], tuple(g for *_, g in scored)))
    for name in ("possession", "pass_completion"):
        h, a = (facts.get(f"{mid}/{name}/match/{team}") for team in (meta.home, meta.away))
        if h is not None and a is not None:
            text = words["share"].format(
                label=words[name], h=h.display, home=home, a=a.display, away=away
            )
            parts.append((text, [h.fact_id, a.fact_id], (end,)))
    flow = facts.get(f"{mid}/chaos_reading/match/all")
    if flow is not None and flow.value in words["flow"]:
        phrase = PHRASES[lang][flow.value]
        parts.append((words["flow"][flow.value].format(phrase), [flow.fact_id], (end,)))
    shown: list[tuple[str, list[str], tuple[str, ...]]] = []
    for part in parts:  # in order, up to the first that does not fit
        if len(_join([*shown, part])) > RECAP_MAX_TEXT:
            break
        shown.append(part)
    claims = tuple(Claim(text, tuple(ids), events) for text, ids, events in shown)
    return Draft(_join(shown), claims)


def _join(parts) -> str:
    return " ".join(f"{text}." for text, _, _ in parts)


@cache
def _clubs() -> dict[str, str]:
    return {c.id: c.name for c in load_league().clubs}

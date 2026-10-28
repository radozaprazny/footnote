import dataclasses
import json
import random
import re
from unittest import mock

import pytest
import real
from hypothesis import given
from hypothesis import strategies as st

from matchlens.cli import main
from matchlens.events import EventType, Outcome, frame_time
from matchlens.explain.state import Lang
from matchlens.facts import WINDOW_MS, display_minute, facts_at
from matchlens.league import load_league
from matchlens.render import cues as cues_module
from matchlens.render.cues import (
    ORDER,
    PERSONAS,
    Cue,
    CueKind,
    CueRendition,
    chance_due,
    cue_timeline,
    ordered,
    window_times,
)
from matchlens.stats.readings import PHRASES
from matchlens.stats.speed import hard_shot_tags

# 0: shots off the woodwork and hard shots on target; 3: five goals, no hard shot on target;
# 7: five goals, one hard shot on target
SEEDS = (0, 3, 7)


PHRASES_IN = {  # by language, any phrase of the vocabulary there
    lang: re.compile(
        r"\b(?:"
        + "|".join(re.escape(p) for p in sorted(set(words.values()), key=len, reverse=True))
        + r")\b",
        re.IGNORECASE,
    )
    for lang, words in PHRASES.items()
}
PHRASE = PHRASES_IN["en"]


def cited(seed: int, cue: Cue, fact_ids: tuple[str, ...] | None = None) -> list:
    """The facts `fact_ids` (else the cue's own) name, from the engine at the cue's moment; for
    the recap also each goal's minute and the score it made, at the goal's instant."""
    by_id = {f.fact_id: f for f in real.facts(seed)}
    by_id |= {f.fact_id: f for f in facts_at(real.match(seed), *cue.due)}
    if cue.kind is CueKind.RECAP:
        by_id |= {f.fact_id: f for f in goal_instants(seed)}
    return [by_id[i] for i in (cue.fact_ids if fact_ids is None else fact_ids)]


def goal_instants(seed: int) -> list:
    """The minute and the score of each goal's instant, from `facts_at` there."""
    m = real.match(seed)
    return [
        f
        for e in m.events
        if e.type is EventType.GOAL
        for f in facts_at(m, e.period, e.clock_ms)
        if f.name in ("minute", "score") and f.fact_id.split("/")[2][:3] in ("at-", "to-")
    ]


def renditions(cue: Cue) -> list[CueRendition]:
    """What each persona reads of `cue`, the analyst first, in English and in each language."""
    there = [cue.translated(p, lang) for lang in Lang for p in PERSONAS]
    return [cue.rendition(p) for p in PERSONAS] + there


def short(team: str) -> str:
    return next(c.short_name for c in load_league().clubs if c.id == team)


def pair(at: dict, name: str, scope: str, home: str, away: str, label: str) -> str | None:
    """The line a cue writes for a pair of team facts, or None if the engine has no pair."""
    h, a = at.get(f"{name}/{scope}/{home}"), at.get(f"{name}/{scope}/{away}")
    if h is None or a is None:
        return None
    return f"{label} {short(home)} {h.display} – {a.display} {short(away)}"


def player_name(player: str) -> str:
    return next(p.name for c in load_league().clubs for p in c.players if p.id == player)


def scorer_line(player: str, due) -> str:
    """`Name #7 · 68'`: shirt number from the league, minute as football counts it."""
    number = next(p.number for c in load_league().clubs for p in c.players if p.id == player)
    return f"{player_name(player)} #{number} · {display_minute(*due)}"


# --- what a cue may say -------------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_every_numeral_of_a_cue_is_the_display_of_a_fact_it_cites(seed):
    """Every cue of the match, not a sample: the cues are few and cached; with the stats-only
    moment cues (a narrative may write a cited number in another form the Guard accepts). Each
    persona's rendition cites its own facts."""
    for cue in real.timeline(seed):
        assert [r.persona for r in cue.renditions] == ["fan"]
        for r in renditions(cue):
            displays = sorted(
                {f.display for f in cited(seed, cue, r.fact_ids)}, key=len, reverse=True
            )
            for line in r.lines:
                rest = line
                for d in displays:
                    rest = rest.replace(d, " ")
                assert not re.search(r"\d", rest), (r.persona, line, displays)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_cue_knows_nothing_from_after_it_is_due(seed):
    """Every cited fact is the one `facts_at(due)` gives, or a whole-match fact whose evidence
    ends at or before `due`; every cue of the match, moment cues included. Only the recap, due
    at the final whistle, cites any whole-match fact and a goal's minute or score."""
    whole = {f.fact_id: f for f in real.facts(seed)}
    goals = {f.fact_id: f for f in goal_instants(seed)}
    recaps = 0
    for cue in real.timeline(seed):
        now = {f.fact_id: f for f in facts_at(real.match(seed), *cue.due)}
        recap = cue.kind is CueKind.RECAP
        recaps += recap
        for fact_id in (i for r in renditions(cue) for i in r.fact_ids):
            fact = now.get(fact_id) or whole.get(fact_id) or (goals[fact_id] if recap else None)
            assert fact is not None and fact.end <= cue.due, fact_id
            if fact_id not in now and not recap:
                assert fact.name == "shot_speed", fact_id
    assert recaps == 1


@pytest.mark.parametrize("seed", SEEDS)
def test_every_id_a_cue_names_exists(seed):
    m = real.match(seed)
    events = {e.event_id: e for e in m.events}
    for cue in real.timeline(seed):  # moment cues included
        for r in renditions(cue):
            assert len(cited(seed, cue, r.fact_ids)) == len(r.fact_ids) == len(set(r.fact_ids))
            assert r.event_ids == cue.event_ids  # the trigger, whoever reads it
            for event_id in r.event_ids:
                e = events[event_id]
                assert (e.period, e.clock_ms) <= cue.due
        for frame_id in cue.frame_ids:
            match_id, period, clock_ms = frame_time(frame_id)
            assert match_id == m.meta.match_id and (period, clock_ms) <= cue.due
            m.frame_at(period, clock_ms)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_phrase_is_a_cited_reading_of_the_club_named_last_before_it(seed):
    """The Guard's phrase rule on every rendition's lines, in every language: a vocabulary phrase
    is the phrase there of a reading the rendition cites, of the club whose short name comes last
    before it in the line, or of no club; every cited reading is said; a window's readings are of
    its last 5 minutes, every other cue's are not."""
    clubs = {c.short_name: c.id for c in load_league().clubs}
    named = re.compile(r"\b(?:" + "|".join(clubs) + r")\b")
    said = 0
    for cue in real.timeline(seed):
        for r in renditions(cue):
            readings = [f for f in cited(seed, cue, r.fact_ids) if f.name.endswith("_reading")]
            for f in readings:
                last5 = f.fact_id.split("/")[2].startswith("last5-")
                assert last5 == (cue.kind is CueKind.WINDOW), f.fact_id
                phrase = PHRASES[r.lang][f.value]
                assert any(phrase in line for line in r.lines), (f.fact_id, r.lines)
            for line in r.lines:
                for m in PHRASES_IN[r.lang].finditer(line):
                    before = named.findall(line[: m.start()])
                    club = clubs[before[-1]] if before else None
                    backed = [f for f in readings if PHRASES[r.lang][f.value] == m.group()]
                    assert any(f.team in (None, club) for f in backed), (r.persona, line, backed)
                    said += 1
    assert said >= 18  # every window's fan line judges, at least


def test_facts_of_another_match_are_refused():
    with pytest.raises(ValueError, match="another match than m7"):
        cue_timeline(real.match(7), real.facts(3))


@pytest.mark.parametrize("seed", SEEDS)
def test_the_timeline_is_deterministic_sorted_and_json(seed):
    first = cue_timeline(real.match(seed), real.facts(seed))
    assert first == real.cues(seed) == cue_timeline(real.match(seed), list(real.facts(seed)))
    keys = [(c.due, ORDER.index(c.kind), c.cue_id) for c in first]
    assert keys == sorted(keys)
    assert len({c.cue_id for c in first}) == len(first)
    for c in first:
        doc = json.loads(json.dumps(c.to_dict(), allow_nan=False))
        assert doc["due"] == list(c.due) and doc["kind"] == c.kind.value
        assert doc["lines"] == list(c.lines) and doc["fact_ids"] == list(c.fact_ids)
        assert doc == c.to_dict() and set(doc["renditions"]) == {"fan"}
        assert c.ttl_ms > 0 and c.lines


def test_the_json_of_a_goal_and_a_half_time_cue_of_match_7():
    """The contract the stream and the page read, written out once (values from 21 Oct)."""
    docs = {c.cue_id: c.to_dict() for c in real.cues(7)}
    assert docs["m7/cue/goal/m7-e00073"] == {
        "cue_id": "m7/cue/goal/m7-e00073",
        "match_id": "m7",
        "due": [1, 258931],
        "kind": "goal",
        "lines": ["GOAL · COR", "Adrien Pellacourt #19 · 5'", "SLT 0–1 COR"],
        "fact_ids": [
            "m7/shirt_number/league/cor-p18",
            "m7/minute/at-1-258931/all",
            "m7/score/to-1-258931/all",
        ],
        "team": "cor",
        "event_ids": ["m7-e00072", "m7-e00073"],
        "frame_ids": [],
        "ttl_ms": 8000,
        "anchor": [6.91, 28.89],
        "renditions": {
            "fan": {
                "lines": ["GOAL · Adrien Pellacourt #19", "COR take the lead", "SLT 0–1 COR"],
                "fact_ids": [
                    "m7/shirt_number/league/cor-p18",
                    "m7/goal_reading/at-1-258931/cor",
                    "m7/score/to-1-258931/all",
                ],
                "event_ids": ["m7-e00072", "m7-e00073"],
            }
        },
        "translations": {
            "sk": {
                "analyst": {
                    "lines": ["GÓL · COR", "Adrien Pellacourt #19 · 5'", "SLT 0–1 COR"],
                    "fact_ids": [
                        "m7/shirt_number/league/cor-p18",
                        "m7/minute/at-1-258931/all",
                        "m7/score/to-1-258931/all",
                    ],
                    "event_ids": ["m7-e00072", "m7-e00073"],
                },
                "fan": {
                    "lines": ["GÓL · Adrien Pellacourt #19", "COR ide do vedenia", "SLT 0–1 COR"],
                    "fact_ids": [
                        "m7/shirt_number/league/cor-p18",
                        "m7/goal_reading/at-1-258931/cor",
                        "m7/score/to-1-258931/all",
                    ],
                    "event_ids": ["m7-e00072", "m7-e00073"],
                },
            }
        },
    }
    assert docs["m7/cue/period_end/m7-e00829"] == {
        "cue_id": "m7/cue/period_end/m7-e00829",
        "match_id": "m7",
        "due": [1, 2773738],
        "kind": "period_end",
        "lines": [
            "Half time",
            "SLT 1–1 COR",
            "Possession SLT 49% – 51% COR",
            "Pass completion SLT 82% – 80% COR",
        ],
        "fact_ids": [
            "m7/score/to-1-2773738/all",
            "m7/possession/to-1-2773738/slt",
            "m7/possession/to-1-2773738/cor",
            "m7/pass_completion/to-1-2773738/slt",
            "m7/pass_completion/to-1-2773738/cor",
        ],
        "team": None,
        "event_ids": ["m7-e00829"],
        "frame_ids": [],
        "ttl_ms": 10000,
        "anchor": None,
        "renditions": {
            "fan": {
                "lines": [
                    "Half time",
                    "SLT 1–1 COR",
                    "SLT and COR have an even share of the ball · a steady tempo",
                ],
                "fact_ids": [
                    "m7/score/to-1-2773738/all",
                    "m7/possession_reading/to-1-2773738/slt",
                    "m7/possession_reading/to-1-2773738/cor",
                    "m7/chaos_reading/to-1-2773738/all",
                ],
                "event_ids": ["m7-e00829"],
            }
        },
        "translations": {
            "sk": {
                "analyst": {
                    "lines": [
                        "Polčas",
                        "SLT 1–1 COR",
                        "Držanie lopty SLT 49% – 51% COR",
                        "Úspešnosť prihrávok SLT 82% – 80% COR",
                    ],
                    "fact_ids": [
                        "m7/score/to-1-2773738/all",
                        "m7/possession/to-1-2773738/slt",
                        "m7/possession/to-1-2773738/cor",
                        "m7/pass_completion/to-1-2773738/slt",
                        "m7/pass_completion/to-1-2773738/cor",
                    ],
                    "event_ids": ["m7-e00829"],
                },
                "fan": {
                    "lines": [
                        "Polčas",
                        "SLT 1–1 COR",
                        "SLT a COR majú rovnaký podiel lopty · rovnomerné tempo",
                    ],
                    "fact_ids": [
                        "m7/score/to-1-2773738/all",
                        "m7/possession_reading/to-1-2773738/slt",
                        "m7/possession_reading/to-1-2773738/cor",
                        "m7/chaos_reading/to-1-2773738/all",
                    ],
                    "event_ids": ["m7-e00829"],
                },
            }
        },
    }
    ttl = {c.kind: c.ttl_ms for c in real.cues(7)}
    assert ttl == {
        CueKind.PERIOD_END: 10_000,
        CueKind.GOAL: 8_000,
        CueKind.CHANCE: 5_000,
        CueKind.WINDOW: 6_000,
    }


# --- which cues, when ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_one_cue_per_goal_chance_period_end_and_fifth_minute(seed):
    m = real.match(seed)
    by_kind = {k: [c for c in real.cues(seed) if c.kind is k] for k in CueKind}
    ends = {e.period: e for e in m.events if e.type is EventType.PERIOD_END}
    goals = [e for e in m.events if e.type is EventType.GOAL]
    assert [c.due for c in by_kind[CueKind.GOAL]] == [(e.period, e.clock_ms) for e in goals]
    chances = [
        e
        for e in m.events
        if e.type is EventType.SHOT
        and e.outcome in (Outcome.SAVED, Outcome.WOODWORK)
        and e.clock_ms + e.duration_ms <= ends[e.period].clock_ms
    ]
    assert [c.event_ids for c in by_kind[CueKind.CHANCE]] == [(e.event_id,) for e in chances]
    assert [c.due for c in by_kind[CueKind.CHANCE]] == [
        (e.period, e.clock_ms + e.duration_ms) for e in chances
    ]
    assert [c.due for c in by_kind[CueKind.PERIOD_END]] == [
        (p, e.clock_ms) for p, e in ends.items()
    ]
    windows = [(p, t) for p, e in ends.items() for t in window_times(e.clock_ms)]
    assert [c.due for c in by_kind[CueKind.WINDOW]] == windows  # a real match always has some


@pytest.mark.parametrize("seed", SEEDS)
def test_a_goal_cue_shows_the_score_with_that_goal_and_not_before(seed):
    """Pinned on the boundary: at the goal's instant the score counts it, 1 ms earlier not."""
    m = real.match(seed)
    meta, short = m.meta, {c.id: c.short_name for c in load_league().clubs}
    events = {e.event_id: e for e in m.events}
    for cue in (c for c in real.cues(seed) if c.kind is CueKind.GOAL):
        shot, goal = (events[i] for i in cue.event_ids)
        assert goal.related == shot.event_id and cue.team == shot.team
        assert cue.anchor == (shot.start.x, shot.start.y)
        so_far = [e for e in m.events if e.type is EventType.GOAL and e.period * 10**9 + e.clock_ms
                  <= goal.period * 10**9 + goal.clock_ms]  # fmt: skip
        home = sum(e.team == meta.home for e in so_far)
        score = f"{home}–{len(so_far) - home}"
        assert f"{short[meta.home]} {score} {short[meta.away]}" in cue.lines
        assert cue.lines[0] == f"GOAL · {short[shot.team]}"
        assert cue.lines[1] == scorer_line(shot.player, cue.due)
        before = facts_at(m, goal.period, goal.clock_ms - 1)
        assert not any(f.name == "score" and f.display == score for f in before)
        assert any(f"/score/to-{goal.period}-{goal.clock_ms}/" in i for i in cue.fact_ids)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_shot_speed_line_exactly_for_a_hard_shot(seed):
    hard = {t.source_ids[0]: t for t in hard_shot_tags(real.match(seed).events)}
    shots = [c for c in real.cues(seed) if c.kind in (CueKind.GOAL, CueKind.CHANCE)]
    seen = 0
    for cue in shots:
        speed = [line for line in cue.lines if line.startswith("Shot speed ")]
        if cue.event_ids[0] in hard:
            seen += 1
            assert speed and speed[0].endswith(" km/h")
            assert any("/shot_speed/" in i for i in cue.fact_ids)
        else:
            assert not speed and not any("/shot_speed/" in i for i in cue.fact_ids)
    assert seen == {0: 5, 3: 0, 7: 1}[seed]  # counted from the matches, 21 Oct


@pytest.mark.parametrize("seed", SEEDS)
def test_chance_cues_say_saved_or_woodwork(seed):
    events = {e.event_id: e for e in real.match(seed).events}
    for cue in (c for c in real.cues(seed) if c.kind is CueKind.CHANCE):
        shot = events[cue.event_ids[0]]
        word = {Outcome.SAVED: "Saved", Outcome.WOODWORK: "Off the woodwork"}[shot.outcome]
        assert cue.lines[0] == f"{word} · {short(shot.team)}"
        assert cue.lines[1] == scorer_line(shot.player, cue.due)
        assert cue.team == shot.team and cue.anchor == (shot.start.x, shot.start.y)


def test_a_chance_is_due_when_the_ball_arrives_up_to_the_period_end():
    """Pinned on the boundary: arriving exactly at the period's end is a cue, 1 ms later none."""
    shot = next(c for c in real.cues(7) if c.kind is CueKind.CHANCE).event_ids[0]
    shot = next(e for e in real.match(7).events if e.event_id == shot)
    arrives = shot.clock_ms + shot.duration_ms
    assert chance_due(shot, arrives) == (shot.period, arrives)
    assert chance_due(shot, arrives + 1) == (shot.period, arrives)
    assert chance_due(shot, arrives - 1) is None
    late = dataclasses.replace(shot, clock_ms=shot.clock_ms + 1)
    assert chance_due(late, arrives) is None


def test_cues_due_together_are_ordered_by_kind_then_id():
    cues = [
        Cue(f"m/cue/{k.value}/{n}", "m", (1, 600_000), k, ("x",), ()) for k in CueKind for n in "ba"
    ]
    later = Cue("m/cue/goal/0", "m", (1, 600_001), CueKind.GOAL, ("x",), ())
    shuffled = [later, *cues]
    random.Random(0).shuffle(shuffled)
    assert [(c.kind, c.cue_id[-1]) for c in ordered(shuffled)[:-1]] == [
        (k, n) for k in ORDER for n in "ab"
    ]
    assert ordered(shuffled)[-1] is later
    assert ORDER == (
        CueKind.PERIOD_END,
        CueKind.GOAL,
        CueKind.CHANCE,
        CueKind.MOMENT,  # after the goal or chance it explains
        CueKind.WINDOW,
        CueKind.RECAP,  # after the full-time cue
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_no_card_names_a_players_top_speed(seed):
    """Outfield players close down at 6.5 m/s (measured top speeds 6.10–6.63 m/s, seeds 0–49), far
    below a real top speed, so no card shows one (issue #7): no rendition of any cue, moment cues
    and the recap included, in any persona or language, cites a top-speed fact or names it; the
    engine still has the fact. Both period ends alike: half time and full time end with their pairs,
    no frame ids."""
    whole = real.facts(seed)
    assert any(f.name == "top_speed" for f in whole)  # the engine keeps it
    tops = {f.fact_id for f in whole if f.name == "top_speed"}
    labels = ("Top speed", "Najvyššia rýchlosť")  # the line's words, English and Slovak
    for cue in real.timeline(seed):
        for r in renditions(cue):
            assert not tops & set(r.fact_ids), cue.cue_id
            assert not any(label in line for line in r.lines for label in labels), r.lines
    ends = [c for c in real.cues(seed) if c.kind is CueKind.PERIOD_END]
    assert [c.lines[0] for c in ends] == ["Half time", "Full time"]
    assert all(not c.frame_ids and len(c.lines) == 4 for c in ends), [c.lines for c in ends]


@pytest.mark.parametrize("seed", SEEDS)
def test_period_end_cues_give_score_possession_and_pass_completion(seed):
    """The lines rebuilt from `facts_at` at the period's end (an oracle independent of the
    builder's lookups)."""
    m = real.match(seed)
    meta = m.meta
    ends = [e for e in m.events if e.type is EventType.PERIOD_END]
    cues = [c for c in real.cues(seed) if c.kind is CueKind.PERIOD_END]
    for end, cue in zip(ends, cues, strict=True):
        at = {f.fact_id.split("/", 1)[1]: f for f in facts_at(m, end.period, end.clock_ms)}
        scope = f"to-{end.period}-{end.clock_ms}"
        score = at[f"score/{scope}/all"].display
        expected = [
            "Half time" if end.period == 1 else "Full time",
            f"{short(meta.home)} {score} {short(meta.away)}",
            pair(at, "possession", scope, meta.home, meta.away, "Possession"),
            pair(at, "pass_completion", scope, meta.home, meta.away, "Pass completion"),
        ]
        assert None not in expected  # a real match has both pairs at each period's end
        assert list(cue.lines[:4]) == expected
        assert len(cue.lines) == 4
        assert cue.event_ids == (end.event_id,) and cue.team is None and cue.anchor is None


@pytest.mark.parametrize("seed", SEEDS)
def test_window_cues_speak_of_the_last_five_minutes(seed):
    for cue in (c for c in real.cues(seed) if c.kind is CueKind.WINDOW):
        period, clock_ms = cue.due
        assert clock_ms % WINDOW_MS == 0 and cue.team is None and not cue.event_ids
        assert all(
            f"/last5-{period}-{clock_ms}/" in i or f"/at-{period}-{clock_ms}/" in i
            for i in cue.fact_ids
        )
        at = {f.fact_id.split("/", 1)[1]: f for f in facts_at(real.match(seed), *cue.due)}
        meta, scope = real.match(seed).meta, f"last5-{period}-{clock_ms}"
        chaos = at.get(f"chaos/{scope}/all")
        expected = [
            f"Recent play to {at[f'clock/at-{period}-{clock_ms}/all'].display}",
            pair(at, "momentum", scope, meta.home, meta.away, "Momentum"),
            pair(at, "pressing_per_minute", scope, meta.home, meta.away, "Pressing / min"),
            None if chaos is None else f"Chaos index {chaos.display}",
        ]
        assert list(cue.lines) == [line for line in expected if line is not None]
        assert len(cue.lines) > 1


# --- window times: on the boundary and one unit off ---------------------------------------------


@pytest.mark.parametrize(
    ("end_ms", "times"),
    [
        (WINDOW_MS - 1, []),
        (WINDOW_MS, []),  # the period cue speaks at its end
        (WINDOW_MS + 1, [WINDOW_MS]),
        (2 * WINDOW_MS, [WINDOW_MS]),
        (2 * WINDOW_MS + 1, [WINDOW_MS, 2 * WINDOW_MS]),
    ],
)
def test_window_times_on_the_boundary(end_ms, times):
    assert window_times(end_ms) == times


@given(st.integers(0, 4 * 60 * 60_000))
def test_window_times_are_every_fifth_minute_before_the_end(end_ms):
    times = window_times(end_ms)
    assert times == [WINDOW_MS * (k + 1) for k in range(len(times))]
    assert all(t < end_ms for t in times)
    assert times[-1:] == [] or times[-1] + WINDOW_MS >= end_ms


# --- the fan's lines ----------------------------------------------------------------------------


def fan(cue: Cue) -> tuple[str, ...]:
    return cue.rendition("fan").lines


@pytest.mark.parametrize("seed", SEEDS)
def test_the_fan_reads_a_goal_as_scorer_what_it_does_for_the_club_and_score(seed):
    """Rebuilt from `facts_at` at the goal (an oracle independent of the builder's lookups)."""
    m = real.match(seed)
    by_id = {e.event_id: e for e in m.events}
    goals = [c for c in real.cues(seed) if c.kind is CueKind.GOAL]
    assert goals
    for cue in goals:
        shot, goal = (by_id[i] for i in cue.event_ids)
        at = {f.fact_id: f for f in facts_at(m, *cue.due)}
        reading = at[f"{m.meta.match_id}/goal_reading/at-{cue.due[0]}-{cue.due[1]}/{goal.team}"]
        who = scorer_line(shot.player, cue.due).rsplit(" · ", 1)[0]
        assert fan(cue) == (f"GOAL · {who}", f"{short(goal.team)} {reading.display}", cue.lines[2])
        assert reading.fact_id in cue.rendition("fan").fact_ids
        assert reading.display in {"take the lead", "equalise", "extend the lead", "pull one back"}


@pytest.mark.parametrize("seed", SEEDS)
def test_the_fan_reads_a_chance_as_its_club_the_player_and_a_hard_shot_s_speed(seed):
    for cue in (c for c in real.cues(seed) if c.kind is CueKind.CHANCE):
        player = cue.lines[1].rsplit(" · ", 1)[0]  # without the minute
        assert fan(cue) == (cue.lines[0], player, *cue.lines[2:])  # the speed line, if any


def test_the_fan_reads_a_window_as_momentum_or_possession_and_the_tempo():
    """Both sides of a pair: the same reading names both clubs, the favoured one only its club,
    home or away; without a momentum reading (a window's action weight under 10) possession."""
    windows = {c.cue_id: c for c in real.cues(7) if c.kind is CueKind.WINDOW}
    assert fan(windows["m7/cue/window/1-300000"]) == (
        "Recent play to 05:00",
        "SLT and COR evenly matched · a steady tempo",
    )
    assert fan(windows["m7/cue/window/1-900000"])[1] == "SLT on top · a steady tempo"  # home
    assert fan(windows["m7/cue/window/1-2100000"])[1] == "COR on top · a steady tempo"  # away
    seed20 = {c.cue_id: c for c in cue_timeline(real.match(20), [])}
    quiet = seed20["m20/cue/window/1-1200000"]
    assert quiet.lines[1] == "Momentum QRD 89% – 11% VEL"  # the engine's, but on a weight < 10
    assert quiet.rendition("fan") == CueRendition(
        "fan",
        ("Recent play to 20:00", "QRD have more of the ball · a steady tempo"),
        (
            "m20/clock/at-1-1200000/all",
            "m20/possession_reading/last5-1-1200000/qrd",
            "m20/chaos_reading/last5-1-1200000/all",
        ),
    )


def test_the_fan_reads_a_period_end_as_the_score_possession_and_tempo():
    ends = [c for c in real.cues(0) if c.kind is CueKind.PERIOD_END]
    assert [fan(c) for c in ends] == [
        ("Half time", "VEL 1–0 QRD", "VEL have more of the ball · a steady tempo"),
        ("Full time", "VEL 1–0 QRD", "VEL and QRD have an even share of the ball · a steady tempo"),
    ]
    assert ends[0].lines[2] == "Possession VEL 55% – 45% QRD"  # 55: more of the ball, exactly
    assert ends[1].lines[2] == "Possession VEL 52% – 48% QRD"


def test_without_a_reading_the_fan_reads_the_analyst_s_lines():
    """The engine without readings: a window's fan lines are the analyst's, a period end's the
    score, a goal's the scorer and the score; no fan line judges."""
    known = cues_module._known

    def unread(match, due):
        return {k: f for k, f in known(match, due).items() if not k[0].endswith("_reading")}

    with mock.patch.object(cues_module, "_known", unread):
        timeline = cue_timeline(real.match(7), real.facts(7))
    for cue in timeline:
        if cue.kind is CueKind.WINDOW:
            assert cue.rendition("fan") == dataclasses.replace(
                cue.rendition("analyst"), persona="fan"
            )
        elif cue.kind is CueKind.PERIOD_END:
            assert fan(cue) == cue.lines[:2]
        elif cue.kind is CueKind.GOAL:
            assert fan(cue)[1:] == cue.lines[2:3]
        assert not any(PHRASE.search(line) for line in fan(cue))


# --- command line -------------------------------------------------------------------------------


def test_cues_command_writes_the_timeline(capsys, tmp_path):
    path = tmp_path / "cues.json"
    assert main(["cues", "--seed", "7", "--out", str(path)]) == 0
    out, err = capsys.readouterr()
    doc = json.loads(path.read_text(encoding="utf-8"))
    cues = [c.to_dict() for c in real.timeline_v2(7)]
    assert out == "" and doc == {"match_id": "m7", "cues": cues}
    assert err == "m7: 61 cues (chance 15, goal 5, moment 20, period_end 2, recap 1, window 18)\n"


def test_cues_command_writes_json_to_stdout_and_the_summary_to_stderr(capsys):
    assert main(["cues", "--seed", "7"]) == 0
    out, err = capsys.readouterr()
    assert out.endswith("\n") and out.count("\n") == 1
    assert json.loads(out)["cues"] == [c.to_dict() for c in real.timeline_v2(7)]
    assert err.startswith("m7: 61 cues ")


def test_cues_command_reports_an_unwritable_file(capsys, tmp_path):
    assert main(["cues", "--seed", "7", "--out", str(tmp_path / "no" / "cues.json")]) == 1
    assert "matchlens cues: cannot write" in capsys.readouterr().err

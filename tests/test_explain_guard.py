"""The Guard: properties on synthetic facts, and the rules on real moments of generated matches."""

import dataclasses
import functools
import re
from collections import Counter

import pytest
from explain_strategies import attempt
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from matchlens.events import EventType, display_clock, make_event_id, make_frame_id
from matchlens.explain.guard import (
    MAX_CLAIMS,
    MAX_TEXT,
    Evidence,
    check,
    judge,
    match_names,
    moment_evidence,
    numerals,
    ordinal,
    stats_only_draft,
    team_names,
)
from matchlens.explain.state import (
    CallError,
    CallFailure,
    Claim,
    Draft,
    MomentCase,
    Reason,
    ReasonCode,
    Verdict,
)
from matchlens.facts import Fact, facts_at, match_facts
from matchlens.generator import generate_match
from matchlens.league import load_league
from matchlens.stats.readings import VOCABULARY

# synthetic: match m7 with events 0-199 and frames of the first minute of period 2
EVENTS = tuple(make_event_id("m7", seq) for seq in range(200))
FRAMES = tuple(make_frame_id("m7", 2, ms) for ms in range(0, 60_000, 100))
NAMES = frozenset({"Corrowmere", "Athletic", "Vellbridge", "Town", "COR", "Brennick", "Wierlo"})
# words that judge nothing ("lead" was one until the readings of M5 made it a judgement word)
FILLER = ("the", "run", "after", "a", "move", "with", "pressure", "and", "at", "now", "for")
END_MS = 1_343_000  # 67:23
STRANGER = "Zorvanek"  # invented: no name of the league, and no real player

plain = st.one_of(
    st.integers(0, 999).map(str), st.builds("{}.{}".format, st.integers(0, 99), st.integers(0, 9))
)
displays = st.one_of(
    plain,
    st.integers(0, 100).map("{}%".format),
    st.builds("{:02d}:{:02d}".format, st.integers(0, 90), st.integers(0, 59)),
    st.integers(1, 90).map("{}'".format),
    st.builds("{}–{}".format, st.integers(0, 9), st.integers(0, 9)),
    st.integers(1, 9).map("45+{}'".format),
)


@st.composite
def facts(draw, n: int) -> list[Fact]:
    """`n` facts with unique ids in every display form the engine writes; a plain number may
    have a unit word, a percentage has `%`, as in `matchlens.facts`."""
    out = []
    for i in range(n):
        name = draw(st.sampled_from(["minute", "score", "possession", "passes", "distance"]))
        if name == "minute":
            display, unit = draw(st.integers(1, 90).map("{}'".format)), ""
        elif draw(st.booleans()):
            display, unit = draw(plain), draw(st.sampled_from(["", "km", "km/h"]))
        else:
            display = draw(displays)
            unit = "%" if display.endswith("%") else ""
        scope = draw(st.sampled_from(["to", "to", "last5"])) if name == "possession" else "to"
        out.append(
            Fact(
                fact_id=f"m7/{name}/{scope}-2-{END_MS}/f{i}",
                match_id="m7",
                name=name,
                value=0,
                unit=unit,
                display=display,
                source="engine",
                start=(1, 0),
                end=(2, END_MS),
                team=draw(st.sampled_from([None, "cor", "vel"])),
                event_ids=tuple(draw(st.lists(st.sampled_from(EVENTS), max_size=4, unique=True))),
                frame_ids=tuple(draw(st.lists(st.sampled_from(FRAMES), max_size=2, unique=True))),
            )
        )
    return out


@st.composite
def worlds(draw):
    """Evidence and a moment of it whose facts are some of the engine's."""
    known = draw(facts(draw(st.integers(1, 6))))
    triggers = draw(st.lists(st.sampled_from(EVENTS), min_size=1, max_size=2, unique=True))
    shown = draw(st.lists(st.sampled_from(known), max_size=len(known), unique_by=id))
    case = MomentCase(
        run_id="r1",
        match_id="m7",
        moment_id="m7-k1",
        trigger_ids=tuple(triggers),
        period=2,
        start_ms=END_MS - 13_000,
        end_ms=END_MS,
        display_clock=display_clock(2, END_MS),
        facts=tuple(f.to_dict() for f in shown),
    )
    facts_by_id = {f.fact_id: f for f in known}
    evidence = Evidence(facts_by_id, frozenset(EVENTS), set(FRAMES).__contains__, NAMES)
    return evidence, case


def forms(fact: Fact) -> list[str]:
    """How the test writes a fact, independent of the Guard's own rule."""
    if fact.name == "minute":
        n = int(fact.display[:-1])
        suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return [fact.display, f"{n}{suffix}"]
    return [fact.display]


def written(fact: Fact, form: str) -> list[str]:
    """The words a fact is written with: the form, a unit word, the window of a last-5 fact."""
    words = [form]
    if fact.unit and fact.unit not in fact.display:
        words.append(fact.unit)
    if "/last5-" in fact.fact_id:
        words += ["in", "the", "last", "5", "minutes"]
    return words


@st.composite
def sound(draw, evidence: Evidence, case: MomentCase):
    """A draft that keeps every rule: per claim, words, cited facts as written and names of the
    match. Returns the draft, the words of each claim and their cited facts."""
    known = list(evidence.facts.values())
    claims_words, cited = [], []
    for _ in range(draw(st.integers(1, 3))):
        mine = draw(st.lists(st.sampled_from(known), min_size=1, max_size=3, unique_by=id))
        words = [draw(st.sampled_from(FILLER))]
        for f in mine:
            words += [draw(st.sampled_from(FILLER)), *written(f, draw(st.sampled_from(forms(f))))]
            if draw(st.booleans()):
                words.append(draw(st.sampled_from(sorted(NAMES))))
        claims_words.append(words)
        cited.append(mine)
    return _draft(claims_words, cited, case, draw), claims_words, cited


def _draft(claims_words, cited, case, draw=None) -> Draft:
    claims = []
    for words, mine in zip(claims_words, cited, strict=True):
        pool = sorted(set(case.trigger_ids).union(*(f.event_ids for f in mine)))
        events = draw(st.lists(st.sampled_from(pool), min_size=1, unique=True)) if draw else pool
        frames = sorted(set().union(*(f.frame_ids for f in mine)))
        claims.append(Claim(" ".join(words), tuple(f.fact_id for f in mine), events, frames))
    return Draft(" ".join(c.text + "." for c in claims), tuple(claims))


@given(st.data())
def test_a_draft_made_of_cited_displays_passes(data):
    evidence, case = data.draw(worlds())
    draft, _, _ = data.draw(sound(evidence, case))
    verdict = check(draft, case, evidence)
    assert verdict.passed, verdict.reasons


@given(st.data())
def test_in_a_passing_draft_every_digit_is_inside_a_claim_that_cites_a_fact_showing_it(data):
    """An oracle that does not use the Guard's numeral reading: runs of digits only."""
    evidence, case = data.draw(worlds())
    draft, _, _ = data.draw(sound(evidence, case))
    assume(check(draft, case, evidence).passed)
    for run in re.finditer(r"[0-9]+", draft.text):
        ok = False
        for claim in draft.claims:
            for occ in re.finditer(re.escape(claim.text), draft.text):
                if occ.start() <= run.start() and run.end() <= occ.end():
                    shown = [evidence.facts[f].display for f in claim.fact_ids]
                    window = draft.text[: run.start()].endswith("last ") and run.group() == "5"
                    ok = ok or any(run.group() in d for d in shown) or window
        assert ok, (run.group(), draft)


replacements = st.one_of(
    displays,
    st.from_regex(r"[0-9]{1,4}(\.[0-9])?( ?%)?", fullmatch=True),
    st.from_regex(r"[0-9]{1,2} ?[-–] ?[0-9]{1,2}", fullmatch=True),
)


@given(st.data())
def test_any_number_no_cited_fact_displays_is_refused_and_named(data):
    evidence, case = data.draw(worlds())
    draft, words, cited = data.draw(sound(evidence, case))
    i = data.draw(st.integers(0, len(words) - 1))
    spots = [k for k, w in enumerate(words[i]) if numerals(w) and words[i][k - 1] != "last"]
    k = data.draw(st.sampled_from(spots))
    new = data.draw(replacements)
    allowed = {form for mine in cited for f in mine for form in forms(f)}  # any claim's
    assume(numerals(new) and numerals(new)[0] not in {numerals(a)[0] for a in allowed})
    words[i][k] = new
    verdict = check(_draft(words, cited, case), case, evidence)
    assert not verdict.passed
    assert (ReasonCode.NUMBER_NOT_CITED, numerals(new)[0]) in {
        (r.code, r.token) for r in verdict.reasons
    }


number_words = st.sampled_from(
    [
        "two",
        "Nil",
        "zero",
        "brace",
        "hat-trick",
        "ninetieth",
        "eleventh",
        "one-nil",
        "by one",
        "first goal",
        "second shot",
        "one save",
        "doubled",
        "Twice",
        "a dozen",
    ]
)


@given(st.data(), number_words)
def test_a_number_in_words_is_refused(data, word):
    evidence, case = data.draw(worlds())
    draft, _, _ = data.draw(sound(evidence, case))
    claim = draft.claims[0]
    changed = dataclasses.replace(claim, text=f"{claim.text} {word}")
    text = draft.text.replace(claim.text, changed.text, 1)
    verdict = check(Draft(text, (changed, *draft.claims[1:])), case, evidence)
    assert ReasonCode.NUMBER_WORD in {r.code for r in verdict.reasons}


@given(st.data(), st.sampled_from(["event", "known_event", "fact", "frame", "known_frame"]))
def test_a_foreign_or_unknown_id_is_refused(data, kind):
    evidence, case = data.draw(worlds())
    draft, _, cited = data.draw(sound(evidence, case))
    i = data.draw(st.integers(0, len(draft.claims) - 1))
    claim = draft.claims[i]
    allowed_events = set(case.trigger_ids).union(*(f.event_ids for f in cited[i]))
    allowed_frames = set().union(*(f.frame_ids for f in cited[i]))
    if kind == "event":
        bad, field, code = make_event_id("m7", 500), "event_ids", ReasonCode.UNKNOWN_EVENT
    elif kind == "known_event":
        free = [e for e in EVENTS if e not in allowed_events]
        bad, field, code = data.draw(st.sampled_from(free)), "event_ids", ReasonCode.FOREIGN_ID
    elif kind == "fact":
        bad, field, code = "m7/nothing/match/all", "fact_ids", ReasonCode.UNKNOWN_FACT
    elif kind == "frame":
        bad, field, code = make_frame_id("m7", 2, 70_000), "frame_ids", ReasonCode.UNKNOWN_FRAME
    else:
        free = [f for f in FRAMES if f not in allowed_frames]
        bad, field, code = data.draw(st.sampled_from(free)), "frame_ids", ReasonCode.FOREIGN_ID
    changed = dataclasses.replace(claim, **{field: (*getattr(claim, field), bad)})
    claims = draft.claims[:i] + (changed,) + draft.claims[i + 1 :]
    verdict = check(Draft(draft.text, claims), case, evidence)
    assert (code, bad, i) in {(r.code, r.token, r.claim) for r in verdict.reasons}


@given(st.data())
def test_claim_order_and_repeated_runs_do_not_change_the_verdict(data):
    evidence, case = data.draw(worlds())
    draft, _, _ = data.draw(sound(evidence, case))
    if data.draw(st.booleans()):  # overlapping claims: one that is part of another
        first = draft.claims[0]
        head = first.text.rsplit(" ", 1)[0]
        draft = Draft(draft.text, (*draft.claims, dataclasses.replace(first, text=head)))
    if data.draw(st.booleans()):  # also for drafts that fail
        draft = Draft(draft.text + " two 77.", draft.claims)
    shuffled = Draft(draft.text, tuple(data.draw(st.permutations(draft.claims))))
    first, again, other = (check(d, case, evidence) for d in (draft, draft, shuffled))
    assert first == again
    assert first.passed == other.passed
    assert Counter((r.code, r.token) for r in first.reasons) == Counter(
        (r.code, r.token) for r in other.reasons
    )


ids = st.text(max_size=12)
claims_of_anything = st.lists(
    st.builds(Claim, st.text(), st.lists(ids), st.lists(ids), st.lists(ids)), max_size=4
)


@given(st.data(), st.text(), claims_of_anything)
def test_the_guard_never_raises_on_any_text(data, text, claims):
    evidence, case = data.draw(worlds())
    verdict = check(Draft(text, tuple(claims)), case, evidence)
    assert verdict.passed == (not verdict.reasons)


@given(worlds())
def test_a_stats_only_cue_always_passes(world):
    evidence, case = world
    verdict = check(stats_only_draft(case, evidence), case, evidence)
    assert verdict.passed, verdict.reasons


# the rules one by one, on synthetic facts


def world(*facts: Fact) -> tuple[Evidence, MomentCase]:
    case = MomentCase(
        "r1", "m7", "m7-k1", (EVENTS[0],), 2, END_MS - 1000, END_MS, display_clock(2, END_MS), ()
    )
    return Evidence(
        {f.fact_id: f for f in facts},
        frozenset(EVENTS),
        set(FRAMES).__contains__,
        NAMES,
        frozenset({"Saltreach", "Quintrell"}),
    ), case


def fact(name: str, display: str, unit: str = "", scope: str = "to", who: str = "all") -> Fact:
    """A fact as the engine writes it: `who` is a club (`cor`), a player (`cor-p07`) or `all`."""
    return Fact(
        f"m7/{name}/{scope}-2-{END_MS}/{who}",
        "m7",
        name,
        0,
        unit,
        display,
        "engine",
        (1, 0),
        (2, END_MS),
        team=who if who in ("cor", "vel") else None,
        player=who if "-p" in who else None,
        event_ids=(EVENTS[1],),
    )


def verdict_of(text: str, *claims: tuple[str, tuple[Fact, ...]], facts=()) -> set:
    evidence, case = world(*facts, *(f for _, fs in claims for f in fs))
    draft = Draft(
        text, tuple(Claim(t, tuple(f.fact_id for f in fs), (EVENTS[0],)) for t, fs in claims)
    )
    return {(r.code, r.token) for r in check(draft, case, evidence).reasons}


GOALS_1, GOALS_0 = fact("goals", "1", who="cor"), fact("goals", "0", who="vel")
SCORE, MINUTE = fact("score", "2–1"), fact("minute", "68'", scope="at")


def test_a_claim_covers_a_numeral_only_whole():
    # a claim "1" no longer hides the 10 and the 101 elsewhere
    got = verdict_of(
        "Corrowmere lead 1–0 with 10 shots and 101 passes.",
        ("Corrowmere lead 1–0", (fact("score", "1–0"),)),
        ("1", (GOALS_1,)),
        ("0", (GOALS_0,)),
    )
    assert {
        (ReasonCode.NUMBER_OUTSIDE_CLAIM, "10"),
        (ReasonCode.NUMBER_OUTSIDE_CLAIM, "101"),
    } <= got
    # a claim cut inside a numeral: 58 of the passes, read as 58% of the ball
    got = verdict_of(
        "Corrowmere have 58% of the ball.", ("Corrowmere have 58", (fact("passes", "58"),))
    )
    assert (ReasonCode.NUMBER_OUTSIDE_CLAIM, "58%") in got


def test_overlapping_claims_pass_in_either_order():
    text = "Brennick makes it 2–1 in the 68th minute."
    c0, c1 = ("Brennick makes it 2–1", (SCORE,)), ("2–1 in the 68th minute", (SCORE, MINUTE))
    assert verdict_of(text, c0, c1) == verdict_of(text, c1, c0) == set()


def test_the_last_five_minutes_window_is_read_only_with_its_fact():
    window = fact("possession", "61%", "%", scope="last5", who="cor")
    so_far = fact("possession", "48%", "%", who="cor")
    text = "Corrowmere have 61% in the last 5 minutes."
    assert verdict_of(text, (text[:-1], (window,))) == set()
    assert (
        verdict_of(text.replace("5", "five"), (text[:-1].replace("5", "five"), (window,))) == set()
    )
    # the same words with the so-far fact: the 5 counts and is cited by nothing
    assert (ReasonCode.NUMBER_NOT_CITED, "5") in verdict_of(text, (text[:-1], (so_far,)))
    # the window fact without its window reads as possession so far
    assert (ReasonCode.SCOPE_NOT_NAMED, None) in verdict_of(
        "Corrowmere have 61%.", ("Corrowmere have 61%", (window,))
    )


@pytest.mark.parametrize(
    "phrase",
    [
        "six-yard box",
        "6-yard box",
        "18-yard box",
        "18-yard line",
        "a one-two",
        "a 50-50 ball",
        "a 50-50 challenge",
        "the back four",
        "the back-four",
        "the final third",
        "the attacking third",
        "a third-man run",
        "a nod from the fourth official",
        "a two-footed lunge",
        "a game of two halves",
        "once again",
        "once more",
        "the back three",
        "their back five",
        "a flat back four",
        "the front three",
        "the front trio",
        "the defensive third",
        "the middle third",
        "a 50-50 header",
        "a 50/50 ball",
        "a 50 50 ball",
        "a triple save",
        "a first touch",
        "a first pass",
        "a double save",
    ],
)
def test_football_phrases_with_a_number_are_no_claims(phrase):
    text = f"Brennick makes it 2–1 from {phrase}."
    assert verdict_of(text, ("Brennick makes it 2–1", (SCORE,))) == set()


def test_a_shirt_number_counts_only_as_a_shirt_number():
    shirt = fact("shirt_number", "7", scope="league", who="cor-p07")
    for text in ("No. 7 Brennick scores", "number 7 Brennick", "#7 Brennick", "shirt 7 Brennick"):
        assert verdict_of(text + ".", (text, (shirt,))) == set(), text
    got = verdict_of("Corrowmere have 7 shots.", ("Corrowmere have 7 shots", (shirt,)))
    assert (ReasonCode.NUMBER_NOT_CITED, "7") in got


def test_a_unit_word_must_follow_its_number():
    distance = fact("distance", "10.3", "km", who="cor-p07")
    speed = fact("top_speed", "31.2", "km/h", who="cor-p07")
    assert verdict_of("Brennick ran 10.3 km.", ("Brennick ran 10.3 km", (distance,))) == set()
    assert verdict_of("Brennick hit 31.2 km/h.", ("Brennick hit 31.2 km/h", (speed,))) == set()
    for text in ("Brennick ran 10.3 m", "Brennick ran 10.3 kmh", "Brennick ran 10.3"):
        assert (ReasonCode.NUMBER_NOT_CITED, "10.3") in verdict_of(text + ".", (text, (distance,)))


@pytest.mark.parametrize("char", ["½", "²", "Ⅲ", "٣"])
def test_a_numeric_character_other_than_ascii_digits_is_refused(char):
    text = f"Brennick makes it 2–1 with {char} of the chances."
    got = verdict_of(text, ("Brennick makes it 2–1", (SCORE,)))
    assert (ReasonCode.UNREADABLE_NUMBER, char) in got


def test_minute_ordinals_follow_english():
    table = {
        1: "1st",
        2: "2nd",
        3: "3rd",
        4: "4th",
        11: "11th",
        12: "12th",
        13: "13th",
        21: "21st",
        22: "22nd",
        23: "23rd",
        90: "90th",
        101: "101st",
        111: "111th",
    }
    assert {n: ordinal(n) for n in table} == table
    for n in (1, 2, 3, 11, 21, 68):
        minute = fact("minute", f"{n}'", scope="at")
        text = f"in the {ordinal(n)} minute"
        assert verdict_of(text, (text, (minute,))) == set()
        wrong = f"in the {n}th minute" if not ordinal(n).endswith("th") else f"in the {n}st minute"
        assert verdict_of(wrong, (wrong, (minute,))) != set()


def test_names_after_no_or_a_colon_are_checked_and_foreign_names_anywhere():
    shirt = fact("shirt_number", "7", scope="league", who="cor-p07")
    for text in (f"No. 7 {STRANGER} scores", f"Goal: {STRANGER} scores"):
        claim = (text, (shirt,)) if "No." in text else (text, ())
        got = (
            verdict_of(text + ".", claim)
            if "No." in text
            else verdict_of(text + ". Brennick makes it 2–1.", ("Brennick makes it 2–1", (SCORE,)))
        )
        assert (ReasonCode.UNKNOWN_NAME, STRANGER) in got, text
    # a sentence start is free for ordinary words, not for the league's other clubs and players
    base = "Brennick makes it 2–1"
    assert verdict_of(f"{base}. Pressure builds.", (base, (SCORE,))) == set()
    assert verdict_of(f"{base}. Will they hold on?", (base, (SCORE,))) == set()
    got = verdict_of(f"{base}. Quintrell watches.", (base, (SCORE,)))
    assert (ReasonCode.UNKNOWN_NAME, "Quintrell") in got


def test_a_reason_needs_a_known_code():
    with pytest.raises(ValueError, match="ReasonCode"):
        Reason("bogus", "x")


# real matches


@functools.cache
def match(seed: int):
    return generate_match(seed)


def moment(seed: int, event_type: EventType, nth: int = 0, end_ms: int | None = None):
    m = match(seed)
    e = [e for e in m.events if e.type is event_type][nth]
    end = e.clock_ms if end_ms is None else end_ms
    triggers = (e.related, e.event_id) if e.related else (e.event_id,)
    case = MomentCase(
        run_id="r1",
        match_id=m.meta.match_id,
        moment_id=f"{m.meta.match_id}-k{nth}",
        trigger_ids=triggers,
        period=e.period,
        start_ms=max(0, end - 10_000),
        end_ms=end,
        display_clock=display_clock(e.period, end),
        facts=tuple(f.to_dict() for f in facts_at(m, e.period, end)),
    )
    return case, moment_evidence(m, case)


def real_fact(case: MomentCase, name: str, team: str | None = None) -> dict:
    return next(
        f
        for f in case.facts
        if f["name"] == name
        and f["team"] == team
        and f["fact_id"].split("/")[2][:3] in ("at-", "to-")
    )


def goal_draft(case: MomentCase, minute_as: str | None = None) -> Draft:
    """A narrative of the goal: the score, the minute and the scorer's possession."""
    m = match(int(case.match_id[1:]))
    score, minute = real_fact(case, "score"), real_fact(case, "minute")
    goal = next(e for e in m.events if e.event_id == case.trigger_ids[-1])
    possession = real_fact(case, "possession", goal.team)
    name = sorted(n for n in match_names(m) if n[0].isupper() and len(n) > 3)[0]
    at = minute_as or minute["display"]
    claims = (
        Claim(
            f"it is {score['display']} in the {at} minute",
            (score["fact_id"], minute["fact_id"]),
            (goal.event_id,),
        ),
        Claim(
            f"with {possession['display']} of the ball for {name}",
            (possession["fact_id"],),
            (goal.event_id,),
        ),
    )
    return Draft(f"Goal, {claims[0].text}, {claims[1].text}.", claims)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_every_goal_and_save_of_real_matches_gets_a_stats_only_cue_that_passes(seed):
    m = match(seed)
    for event_type in (EventType.GOAL, EventType.SAVE):
        for nth in range(sum(e.type is event_type for e in m.events)):
            case, evidence = moment(seed, event_type, nth)
            cue = stats_only_draft(case, evidence)
            assert [c.fact_ids[0].split("/")[1] for c in cue.claims][:2] == ["minute", "score"]
            verdict = check(cue, case, evidence)
            assert verdict.passed, (case.moment_id, verdict.reasons)


def test_a_real_goal_narrative_passes_and_each_rule_refuses_its_breach():
    case, evidence = moment(7, EventType.GOAL)
    good = goal_draft(case)
    assert check(good, case, evidence).passed, check(good, case, evidence).reasons
    minute = int(real_fact(case, "minute")["display"].split("+")[0].rstrip("'"))
    assert check(goal_draft(case, minute_as=ordinal(minute)), case, evidence).passed
    c0, c1 = good.claims
    cities = ("Corrowmere", "Vellbridge", "Quarrendale", "Saltreach")
    other_club = next(c for c in cities if c not in match_names(match(7)))
    breaches = {
        ReasonCode.NO_CLAIMS: Draft("Goal.", ()),
        ReasonCode.CLAIM_NOT_IN_TEXT: Draft("Goal.", (c0,)),
        ReasonCode.UNKNOWN_FACT: Draft(
            good.text, (dataclasses.replace(c0, fact_ids=("m7/x",)), c1)
        ),
        ReasonCode.NUMBER_NOT_CITED: Draft(good.text, (dataclasses.replace(c0, fact_ids=()), c1)),
        ReasonCode.NUMBER_OUTSIDE_CLAIM: Draft(good.text + " 98 passes.", good.claims),
        ReasonCode.NUMBER_WORD: Draft(good.text + " Two shots.", good.claims),
        ReasonCode.NO_EVIDENCE: Draft(good.text, (dataclasses.replace(c0, event_ids=()), c1)),
        ReasonCode.UNKNOWN_EVENT: Draft(
            good.text, (dataclasses.replace(c0, event_ids=("m7-e99999",)), c1)
        ),
        ReasonCode.FOREIGN_ID: Draft(
            good.text, (dataclasses.replace(c0, event_ids=(make_event_id("m7", 0),)), c1)
        ),
        ReasonCode.UNKNOWN_FRAME: Draft(
            good.text, (dataclasses.replace(c0, frame_ids=(make_frame_id("m7", 2, 3_000_000),)), c1)
        ),
        ReasonCode.UNKNOWN_NAME: Draft(good.text + f" A cross from {other_club}.", good.claims),
        ReasonCode.UNREADABLE_NUMBER: Draft(good.text + " ½ chance.", good.claims),
        ReasonCode.TOO_LONG: Draft(good.text + " and so on" * 100, good.claims),
        ReasonCode.PHRASE_OUTSIDE_CLAIM: Draft(good.text + " They are on top.", good.claims),
        ReasonCode.PHRASE_NOT_CITED: Draft(
            good.text + " They are on top.",
            (*good.claims, Claim("They are on top", (), c0.event_ids)),
        ),
        ReasonCode.JUDGEMENT_WORD: Draft(good.text + " They lead.", good.claims),
    }
    recap_only = {ReasonCode.NO_FINAL_SCORE}  # test_explain_recap
    translation_only = {ReasonCode.NUMERAL_CHANGED, ReasonCode.NAME_CHANGED}  # test_translate
    elsewhere = {ReasonCode.NO_DRAFT, ReasonCode.SCOPE_NOT_NAMED} | recap_only | translation_only
    assert set(breaches) | elsewhere == set(ReasonCode)
    for code, draft in breaches.items():
        verdict = check(draft, case, evidence)
        assert code in {r.code for r in verdict.reasons}, (code, verdict.reasons)
        assert not verdict.passed


def test_names_of_the_lineups_pass_in_their_forms_and_the_bench_does_not():
    case, evidence = moment(7, EventType.GOAL)
    m = match(7)
    good = goal_draft(case)
    shirt = next(f for f in case.facts if f["name"] == "shirt_number")
    league = load_league()
    player = next(p for c in league.clubs for p in c.players if p.id == shirt["player"])
    surname = player.name.split()[-1]
    no = Claim(f"No. {shirt['display']} {surname}", (shirt["fact_id"],), case.trigger_ids)
    for extra in (f"Great move by {surname}'s side.", f"A {surname}-born cross."):
        verdict = check(Draft(f"{good.text} {extra}", good.claims), case, evidence)
        assert verdict.passed, verdict.reasons
    verdict = check(Draft(f"{good.text} Then {no.text} runs.", (*good.claims, no)), case, evidence)
    assert verdict.passed, verdict.reasons
    lineups = set(m.meta.home_lineup + m.meta.away_lineup)
    club = next(c for c in league.clubs if c.id == m.meta.home)
    bench = next(p for p in club.players if p.id not in lineups).name.split()[-1]
    for stranger in (STRANGER, bench):
        for extra in (f"A pass to {stranger}.", f"{stranger} watches."):
            reasons = check(Draft(f"{good.text} {extra}", good.claims), case, evidence).reasons
            if stranger == STRANGER and extra.startswith(STRANGER):
                assert reasons == ()  # the documented limit: an invented name at a start
            else:
                assert (ReasonCode.UNKNOWN_NAME, stranger) in {(r.code, r.token) for r in reasons}


def test_the_evidence_is_the_engine_at_the_moment():
    m = match(7)
    goal = next(e for e in m.events if e.type is EventType.GOAL)
    on_grid = goal.clock_ms // 100 * 100
    case, evidence = moment(7, EventType.GOAL, end_ms=on_grid)
    assert set(evidence.facts) == {f.fact_id for f in facts_at(m, case.period, case.end_ms)}
    later = next(e for e in m.events if (e.period, e.clock_ms) > (case.period, case.end_ms))
    assert later.event_id not in evidence.event_ids
    mid = m.meta.match_id
    assert evidence.is_frame(make_frame_id(mid, case.period, on_grid))  # the moment's own frame
    assert not evidence.is_frame(make_frame_id(mid, case.period, on_grid + 100))  # the next one
    assert not evidence.is_frame(make_frame_id("m8", 1, 0)) and not evidence.is_frame("junk")
    with pytest.raises(ValueError, match="not of match"):
        moment_evidence(match(1), case)
    player = m.meta.home_lineup[0]  # a whole-match fact (tracking) is not known at the moment
    assert f"{mid}/distance/match/{player}" not in evidence.facts
    names = match_names(m)
    assert {"Meridian", "League"} <= names and len(names) > 22


def test_a_case_whose_facts_are_not_the_engines_is_a_pipeline_bug():
    case, _ = moment(7, EventType.GOAL)
    shown = dict(case.facts[0]) | {"display": "99"}
    with pytest.raises(ValueError, match="not the engine's"):
        moment_evidence(match(7), dataclasses.replace(case, facts=(shown, *case.facts[1:])))
    ghost = dict(case.facts[0]) | {"fact_id": f"{case.match_id}/ghost/match/all"}
    with pytest.raises(ValueError, match="not the engine's"):
        moment_evidence(match(7), dataclasses.replace(case, facts=(ghost,)))


@settings(deadline=None)  # the first example generates the match
@given(st.text(), claims_of_anything)
def test_the_guard_never_raises_with_real_evidence(text, claims):
    case, evidence = _real_goal()
    verdict = check(Draft(text, tuple(claims)), case, evidence)
    assert verdict.passed == (not verdict.reasons)


@functools.cache
def _real_goal():
    return moment(7, EventType.GOAL)


def test_judge_takes_the_last_attempt_and_a_failed_one_has_no_draft():
    case, evidence = moment(7, EventType.GOAL)
    with pytest.raises(ValueError, match="no attempt waiting"):
        judge(case, evidence)
    passed = case.with_attempt(attempt(1, draft=goal_draft(case)))
    assert judge(passed, evidence).passed
    failure = CallFailure(CallError.TIMEOUT, "no answer in 30 s")
    failed = case.with_attempt(dataclasses.replace(attempt(1, draft=None), error=failure))
    verdict = judge(failed, evidence)
    assert [(r.code, r.detail) for r in verdict.reasons] == [
        (ReasonCode.NO_DRAFT, "the attempt failed (timeout): no answer in 30 s")
    ]
    judged = passed.with_verdict(judge(passed, evidence))
    with pytest.raises(ValueError, match="no attempt waiting"):
        judge(judged, evidence)


def test_numerals_are_read_as_displays_are_written():
    text = "45+2:13 then 67:23, 45+3’ and 3 - 2, 52 % with 12.7 km, 68th and 68’; No. 9."
    assert numerals(text) == ["45+2:13", "67:23", "45+3'", "3–2", "52%", "12.7", "68th", "68'", "9"]
    assert numerals("no digits here") == []


@pytest.mark.parametrize("seed", [0, 1])
def test_every_display_of_the_engine_reads_as_itself(seed):
    """Seeds 0-4 were all checked once, 21 Oct (6 303 facts); whole-match facts take ~4 s a
    match (tracking), so CI reads them for seed 0 only."""
    m = match(seed)
    facts = list(match_facts(m)) if seed == 0 else []
    for e in m.events[::50]:
        facts += facts_at(m, e.period, e.clock_ms)
    phrases = {f.display for f in facts if f.name.endswith("_reading")}
    assert phrases and all(numerals(p) == [] for p in phrases)  # a reading shows no number
    shown = [f.display for f in facts if not f.name.endswith("_reading")]
    assert [d for d in shown if numerals(d) != [d]] == []


# review round 2 and the verifier's mutation gaps

# every number word and counted phrase the Guard knows, written out, not read from its regex
NUMBER_WORDS = [
    *[
        "zero",
        "nil",
        "nought",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "third",
        "fourth",
        "fifth",
        "sixth",
        "seventh",
        "eighth",
        "ninth",
        "tenth",
        "eleventh",
        "twelfth",
        "thirteenth",
        "fourteenth",
        "fifteenth",
        "sixteenth",
        "seventeenth",
        "eighteenth",
        "nineteenth",
        "twentieth",
        "thirtieth",
        "fortieth",
        "fiftieth",
        "sixtieth",
        "seventieth",
        "eightieth",
        "ninetieth",
        "hundredth",
        "twice",
        "thrice",
        "dozen",
        "brace",
        "hat-trick",
        "treble",
        "doubled",
        "doubles",
        "apiece",
        "trio",
        "triple",
        "quarter",
    ],
    "hat trick",
    "one goal",
    "one-goal",
    "first goal",
    "first-minute",
    "second shot",
    "single goal",
    "one save",
    "one corner",
    "one attempt",
    "one chance",
    "one tackle",
    "one foul",
    "one win",
    "one point",
    "one assist",
    "one half-chance",
    "one-nil",
    "one all",
    "one-up",
    "one down",
    "by one",
    "a couple of",
    "a pair of",
    "half of",
    "Twenty-first",
    "only once",
    "dozens",
    "hundreds",
    "thousands",
    "millions",
    "tens",
    "twofold",
    "threefold",
    "one more shot",
    "one fewer corner",
    "one clear chance",
    "second league goal",
    "one effort",
    "one strike",
    "one header",
    "one extra cross",
    "just once",
    "more than once",
    "at least once",
    "exactly once",
    "scored once",
    "struck once",
    "netted once",
    "saved once",
]


@pytest.mark.parametrize("word", NUMBER_WORDS)
def test_every_number_word_is_refused(word):
    text = f"Brennick makes it 2–1 with {word} chances."
    got = verdict_of(text, ("Brennick makes it 2–1", (SCORE,)))
    assert ReasonCode.NUMBER_WORD in {code for code, _ in got}, word


def test_50_50_is_no_claim_only_for_a_duel():
    possession = fact("possession", "62%", "%", who="cor")
    got = verdict_of(
        "Possession is 50-50 after Brennick makes it 2–1.",
        ("Brennick makes it 2–1", (SCORE,)),
        facts=(possession,),
    )
    assert (ReasonCode.NUMBER_OUTSIDE_CLAIM, "50–50") in got


@pytest.mark.parametrize("written", ["2:1", "2‑1", "2−1", "2/1", "2 to 1", "2—1", "2 - 1"])
def test_two_numbers_joined_read_as_one_score(written):
    goals = (fact("goals", "2", who="cor"), fact("goals", "1", who="vel"))
    text = f"It is {written}"
    assert (ReasonCode.NUMBER_NOT_CITED, "2–1") in verdict_of(text + ".", (text, goals))
    assert verdict_of(text + ".", (text, (SCORE,))) == set()  # the score fact shows 2–1
    reverse = f"It is {written[::-1]}"
    assert verdict_of(reverse + ".", (reverse, (SCORE,))) != set()  # display order only


def test_a_clock_may_drop_its_leading_zero():
    clock = fact("clock", "09:05", scope="at")
    for written in ("09:05", "9:05"):
        text = f"at {written} it is 2–1"
        assert verdict_of(text, (text, (clock, SCORE))) == set(), written


def test_a_stoppage_minute_is_only_its_display():
    minute = fact("minute", "45+3'", scope="at")
    assert verdict_of("in the 45+3' minute", ("in the 45+3' minute", (minute,))) == set()
    assert verdict_of("in the 45th minute", ("in the 45th minute", (minute,))) != set()


def test_a_shirt_number_needs_its_context_and_the_hint_says_so():
    shirt = fact("shirt_number", "13", scope="league", who="cor-p13")
    for text in ("the 13 shirt of Brennick", "numbers 13 and so on"):
        assert verdict_of(text, (text, (shirt,))) == set(), text
    text = "No. 13 Brennick has 13 shots"
    assert (ReasonCode.NUMBER_NOT_CITED, "13") in verdict_of(text, (text, (shirt,)))
    evidence, case = world(shirt)
    claim = Claim("Brennick (13) scores", (shirt.fact_id,), (EVENTS[0],))
    draft = Draft("Brennick (13) scores.", (claim,))
    (reason,) = check(draft, case, evidence).reasons
    assert "needs 'No.' before it" in reason.detail


def test_a_missing_unit_is_named_in_the_hint():
    distance = fact("distance", "10.3", "km", who="cor-p07")
    evidence, case = world(distance)
    for written, ok in (("10.3km", True), ("10.3 km/h", False), ("10.3 kms", False)):
        claim = Claim(f"Brennick ran {written}", (distance.fact_id,), (EVENTS[0],))
        verdict = check(Draft(claim.text + ".", (claim,)), case, evidence)
        assert verdict.passed == ok, written
        if not ok:
            assert "needs its unit 'km'" in verdict.reasons[0].detail


def test_the_hint_allows_a_fact_with_the_same_number_only_if_the_sentence_states_it():
    goals = fact("goals", "2", who="cor")
    evidence, case = world(goals, SCORE)
    claim = Claim("Corrowmere have 2 shots", (SCORE.fact_id,), (EVENTS[0],))
    (reason,) = check(Draft(claim.text + ".", (claim,)), case, evidence).reasons
    assert reason.code is ReasonCode.NUMBER_NOT_CITED
    assert "goals of cor" in reason.detail
    assert "only if the sentence states exactly" in reason.detail
    claim = Claim("Corrowmere have 9 shots", (SCORE.fact_id,), (EVENTS[0],))
    (reason,) = check(Draft(claim.text + ".", (claim,)), case, evidence).reasons
    assert reason.detail == "no fact of the moment shows 9: drop the number"


def test_names_after_abbreviations_and_in_lower_case():
    base = "Brennick makes it 2–1"
    for extra in (f"No. {STRANGER} runs.", f"It is Brennick vs. {STRANGER}."):
        got = verdict_of(f"{base}. {extra}", (base, (SCORE,)))
        assert (ReasonCode.UNKNOWN_NAME, STRANGER) in got, extra
    assert (ReasonCode.UNKNOWN_NAME, "quintrell") in verdict_of(
        f"{base}. A pass to quintrell.", (base, (SCORE,))
    )
    for fine in ("The town is loud.", "After a VAR check it stands.", "Corrowmere’s fans sing."):
        assert verdict_of(f"{base}. {fine}", (base, (SCORE,))) == set(), fine
    for start in (f'{base}." Pressure builds.', f"{base}.\nPressure builds."):
        assert verdict_of(start, (base, (SCORE,))) == set(), start


def test_a_blank_claim_is_in_no_text_and_order_does_not_change_the_reasons():
    assert (ReasonCode.CLAIM_NOT_IN_TEXT, None) in verdict_of(
        "Brennick makes it 2–1.", ("Brennick makes it 2–1", (SCORE,)), ("  ", (SCORE,))
    )
    text = "A 77 and B 77."
    once = verdict_of(text, ("A 77 and B 77", ()), ("B 77", ()))
    assert once == verdict_of(text, ("B 77", ()), ("A 77 and B 77", ()))
    evidence, case = world()
    claims = (Claim("A 77 and B 77", (), (EVENTS[0],)), Claim("B 77", (), (EVENTS[0],)))
    counts = [len(check(Draft(text, c), case, evidence).reasons) for c in (claims, claims[::-1])]
    assert counts[0] == counts[1]


def test_a_draft_over_the_limits_is_refused_at_once():
    evidence, case = world(SCORE)
    claim = Claim("Brennick makes it 2–1", (SCORE.fact_id,), (EVENTS[0],))
    assert (MAX_TEXT, MAX_CLAIMS) == (1000, 12)  # item 3's prompt states both limits

    def codes(text: str, n_claims: int = 1) -> list:
        return [r.code for r in check(Draft(text, (claim,) * n_claims), case, evidence).reasons]

    text = claim.text + "."
    at_limit = text + " " * (1000 - len(text))
    assert len(at_limit) == 1000 and codes(at_limit) == []
    assert codes(at_limit + " ") == [ReasonCode.TOO_LONG]
    assert codes(text, 12) == []
    assert codes(text, 13) == [ReasonCode.TOO_LONG]


# review round 3 and the verifier's mutation gaps of round 3


@pytest.mark.parametrize(
    "text",
    [
        "Brennick makes it 2–1. Vellbridge hit back five minutes later.",
        "Brennick makes it 2–1. Vellbridge struck back three minutes after the break.",
        "Brennick makes it 2–1. Brennick is the third man to score.",
        "Brennick makes it 2–1. The back four minutes were wild.",
        "Brennick makes it 2–1. Vellbridge scored only once.",
    ],
)
def test_a_number_word_next_to_a_football_phrase_still_counts(text):
    got = verdict_of(text, ("Brennick makes it 2–1", (SCORE,)))
    assert ReasonCode.NUMBER_WORD in {code for code, _ in got}, text


@pytest.mark.parametrize(
    "extra",
    [
        "The back four held.",
        "In the first half of the match it was quiet.",
        "The second half of the game was loud.",
        "Once he was through, Brennick finished.",
        "Someone saves it.",
        "The first goalkeeper to move.",
    ],
)
def test_words_that_only_look_like_numbers_pass(extra):
    base = "Brennick makes it 2–1"
    assert verdict_of(f"{base}. {extra}", (base, (SCORE,))) == set(), extra


COUNTED_AFTER_A_LINE = [
    f"{noun}{plural}"
    for noun in (
        *("goal", "shot", "save", "corner", "minute", "attempt", "chance", "tackle", "foul"),
        *("win", "point", "assist", "half-chance", "second", "time", "min", "sec", "game"),
        *("effort", "yard", "metre", "meter", "player", "hour", "day", "week", "month", "year"),
        "season",
    )
    for plural in ("", "s")
]


@pytest.mark.parametrize("plural", ["passes", "matches", "crosses", "touches", "men", "all"])
def test_a_line_before_an_irregular_plural_is_a_number(plural):
    base = "Brennick makes it 2–1"
    got = verdict_of(f"{base}. Then their back four {plural} came.", (base, (SCORE,)))
    assert ReasonCode.NUMBER_WORD in {code for code, _ in got}, plural


@pytest.mark.parametrize(
    "text",
    [
        "Vellbridge hit back five mins later.",  # no determiner: no line
        "The back four timed it well and fouled nobody.",  # a counted noun is a whole word
        "That back four held.",
        "This back three is deep.",
        "The front-three combined well.",
        "Brennick after a third man run.",
        "Wierlo made a triple save.",
        "Wierlo made triple saves.",
    ],
)
def test_a_line_or_phrase_needs_its_whole_form(text):
    base = "Brennick makes it 2–1"
    got = verdict_of(f"{base}. {text}", (base, (SCORE,)))
    words = {token for code, token in got if code is ReasonCode.NUMBER_WORD}
    assert words == ({"five"} if "mins" in text else set()), text


@pytest.mark.parametrize(
    "text",
    [
        "Wierlo passes to Rhea back four.",  # `a` inside a word is no determiner
        "It's back four held.",  # a contraction is no possessive
        "Brennick's back three held.",
        "Corrowmere's back four held.",  # a known false refusal (Follow-ups)
    ],
)
def test_a_line_needs_a_determiner_word_before_it(text):
    base = "Brennick makes it 2–1"
    got = verdict_of(f"{base}. {text}", (base, (SCORE,)))
    assert ReasonCode.NUMBER_WORD in {code for code, _ in got}, text


def test_the_window_is_only_its_own_minutes():
    window = fact("possession", "61%", "%", scope="last5", who="cor")
    for text in (
        "Corrowmere have 61% in the past 5 minutes",
        "Corrowmere have 61% in the past five minutes",
    ):
        assert verdict_of(text + ".", (text, (window,))) == set(), text
    for text in ("Corrowmere have 61% in the next 5 minutes", "Corrowmere have 61% in 5 minutes"):
        assert (ReasonCode.NUMBER_NOT_CITED, "5") in verdict_of(text + ".", (text, (window,)))
    text = "Corrowmere have 61% in the last six minutes"
    got = verdict_of(text + ".", (text, (window,)))
    assert {(ReasonCode.SCOPE_NOT_NAMED, None), (ReasonCode.NUMBER_WORD, "six")} <= got


@pytest.mark.parametrize("counted", COUNTED_AFTER_A_LINE)
@pytest.mark.parametrize("line", ["the back four ", "the back-four ", "the front three -"])
def test_a_line_before_a_counted_noun_is_a_number(line, counted):
    base = "Brennick makes it 2–1"
    got = verdict_of(f"{base}. Then {line}{counted} came.", (base, (SCORE,)))
    assert ReasonCode.NUMBER_WORD in {code for code, _ in got}, (line, counted)


@pytest.mark.parametrize("determiner", ["the", "a", "their", "his", "its", "our", "flat"])
@pytest.mark.parametrize(
    "line", ["back three", "back four", "back five", "front three", "front trio"]
)
def test_a_line_after_a_determiner_is_no_number(determiner, line):
    base = "Brennick makes it 2–1"
    assert verdict_of(f"{base} past {determiner} {line}.", (base, (SCORE,))) == set()


@pytest.mark.parametrize("run", ["run", "runs", "runner", "runners", "combination", "combinations"])
def test_a_third_man_move_is_no_number(run):
    base = "Brennick makes it 2–1"
    assert verdict_of(f"{base} after a third-man {run}.", (base, (SCORE,))) == set()


@pytest.mark.parametrize("abbreviation", ["e.g.", "i.e.", "E.g.", "I.e.", "v.", "St."])
def test_an_abbreviation_ends_no_sentence(abbreviation):
    base = "Brennick makes it 2–1"
    got = verdict_of(f"{base}, {abbreviation} {STRANGER} runs.", (base, (SCORE,)))
    assert (ReasonCode.UNKNOWN_NAME, STRANGER) in got


def test_a_claim_may_start_and_end_on_a_numeral():
    text = "Now 2–1 for Corrowmere."
    assert verdict_of(text, ("2–1 for Corrowmere", (SCORE,))) == set()
    assert verdict_of(text, ("Now 2–1", (SCORE,))) == set()


def test_a_shirt_number_context_is_read_far_into_a_long_text():
    shirt = fact("shirt_number", "7", scope="league", who="cor-p07")
    lead = "Brennick makes it 2–1 after a long move down the left wing. "
    assert len(lead) > 40
    text = lead + "No. 7 Brennick scores."
    claims = (("Brennick makes it 2–1", (SCORE,)), ("No. 7 Brennick scores", (shirt,)))
    assert verdict_of(text, *claims) == set()
    text = lead + "Brennick with 7 shots."
    got = verdict_of(text, claims[0], ("Brennick with 7 shots", (shirt,)))
    assert (ReasonCode.NUMBER_NOT_CITED, "7") in got


def test_a_whitespace_claim_is_in_no_text_even_where_the_text_has_it():
    got = verdict_of(
        "Brennick makes it 2–1 .", ("Brennick makes it 2–1", (SCORE,)), (" ", (SCORE,))
    )
    assert (ReasonCode.CLAIM_NOT_IN_TEXT, None) in got


def test_two_claims_without_evidence_give_two_reasons():
    evidence, case = world(SCORE)
    claims = (
        Claim("Brennick makes it 2–1", (SCORE.fact_id,), ()),
        Claim("2–1 now", (SCORE.fact_id,), ()),
    )
    verdict = check(Draft("Brennick makes it 2–1 now.", claims), case, evidence)
    assert [(r.code, r.claim) for r in verdict.reasons] == [
        (ReasonCode.NO_EVIDENCE, 0),
        (ReasonCode.NO_EVIDENCE, 1),
    ]


def test_a_score_with_spaces_around_its_dash_reads_as_one_score():
    assert numerals("It is 3 – 2 now") == ["3–2"]
    score = fact("score", "3–2")
    assert verdict_of("It is 3 – 2.", ("It is 3 – 2", (score,))) == set()


@given(st.data())
def test_even_with_stray_claims_and_numbers_a_passing_draft_cites_every_digit(data):
    """An oracle that does not use the Guard's reading of numerals: every run of digits of a
    passing draft is a whole run of digits of a fact its covering claim cites (or the window)."""
    evidence, case = data.draw(worlds())
    draft, _, _ = data.draw(sound(evidence, case))
    text, claims = draft.text, list(draft.claims)
    known = list(evidence.facts.values())
    for _ in range(data.draw(st.integers(0, 3))):
        if data.draw(st.booleans()):  # a number put in somewhere
            at = data.draw(st.integers(0, len(text)))
            number = data.draw(st.sampled_from([" 7", "1", " 52%", "0", " 3–2 "]))
            text = text[:at] + number + text[at:]
        else:  # a claim made of any piece of the narrative, citing any facts
            a = data.draw(st.integers(0, len(text) - 1))
            b = data.draw(st.integers(a + 1, len(text)))
            mine = data.draw(st.lists(st.sampled_from(known), max_size=2, unique_by=id))
            claims.append(Claim(text[a:b], tuple(f.fact_id for f in mine), case.trigger_ids))
    verdict = check(Draft(text, tuple(claims)), case, evidence)
    if not verdict.passed:
        return
    for run in re.finditer(r"[0-9]+", text):
        ok = False
        for claim in claims:
            for occ in re.finditer(re.escape(claim.text), text) if claim.text.strip() else ():
                if not occ.start() <= run.start() <= run.end() <= occ.end():
                    continue
                cited = [evidence.facts[f] for f in claim.fact_ids if f in evidence.facts]
                runs = {r for f in cited for r in re.findall(r"[0-9]+", f.display)}
                window = text[: run.start()].endswith("last ") and any(
                    "/last5-" in f.fact_id for f in cited
                )
                ok = ok or run.group() in runs or window
        assert ok, (run.group(), text, claims)


def test_judge_reads_the_last_attempt():
    case, evidence = moment(7, EventType.GOAL)
    good, bad = goal_draft(case), Draft("Goal, 99 shots.", goal_draft(case).claims)
    rejected = Verdict(False, (Reason(ReasonCode.NUMBER_WORD, "x", "two"),))
    first_bad = case.with_attempt(attempt(1, draft=bad)).with_verdict(rejected)
    assert judge(first_bad.with_attempt(attempt(2, draft=good)), evidence).passed
    first_good = case.with_attempt(attempt(1, draft=good)).with_verdict(rejected)
    assert not judge(first_good.with_attempt(attempt(2, draft=bad)), evidence).passed


def test_club_names_and_plain_words_pass_with_real_evidence():
    case, evidence = moment(7, EventType.GOAL)
    m = match(7)
    good = goal_draft(case)
    club = next(c for c in load_league().clubs if c.id == m.meta.home)
    for extra in (f"A fine move by {club.name}.", "Will they hold on? I think so."):
        verdict = check(Draft(f"{good.text} {extra}", good.claims), case, evidence)
        assert verdict.passed, (extra, verdict.reasons)


def test_a_frame_of_the_first_half_after_its_end_is_no_frame():
    m = match(7)
    goals = [e for e in m.events if e.type is EventType.GOAL]
    nth = next(k for k, e in enumerate(goals) if e.period == 2)
    case, evidence = moment(7, EventType.GOAL, nth=nth)
    last = max(s.clock_ms for s in m.snapshots if s.period == 1) // 100 * 100
    assert evidence.is_frame(make_frame_id(m.meta.match_id, 1, last))
    assert not evidence.is_frame(make_frame_id(m.meta.match_id, 1, last + 200))


def test_a_real_stats_only_cue_has_minute_score_and_both_possessions():
    case, evidence = moment(7, EventType.SAVE, 3)
    cue = stats_only_draft(case, evidence)
    assert [c.fact_ids[0].split("/")[1] for c in cue.claims] == [
        "minute",
        "score",
        "possession",
        "possession",
    ]


# --- readings: the only words that judge the score or the play --------------------------------

READING_SEEDS = (0, 1, 3)


@functools.cache
def real_moments() -> list[tuple[MomentCase, Evidence]]:
    """Every goal and save of the matches of the measured runs, at the moment it ends."""
    cases = []
    for seed in READING_SEEDS:
        m = match(seed)
        for kind in (EventType.GOAL, EventType.SAVE):
            for nth in range(sum(e.type is kind for e in m.events)):
                cases.append(moment(seed, kind, nth))
    return cases


def club_name(case: MomentCase, team: str) -> str:
    return next(c.name for c in load_league().clubs if c.id == team)


def reading_claims(case: MomentCase, evidence: Evidence, chosen) -> list[Claim]:
    """One claim per chosen reading: its club's name, then its phrase (and the window)."""
    claims = []
    for f in chosen:
        who = club_name(case, f.team) if f.team else "The play is"
        window = " in the last 5 minutes" if "/last5-" in f.fact_id else ""
        claims.append(Claim(f"{who} {f.display}{window}", (f.fact_id,), case.trigger_ids[-1:]))
    return claims


def readings_of(evidence: Evidence) -> list[Fact]:
    return sorted(
        (f for f in evidence.facts.values() if f.name.endswith("_reading")),
        key=lambda f: f.fact_id,
    )


@settings(deadline=None)
@given(st.data())
def test_a_caption_of_cited_readings_and_displays_passes(data):
    case, evidence = data.draw(st.sampled_from(real_moments()))
    readings = st.sampled_from(readings_of(evidence))
    chosen = data.draw(st.lists(readings, min_size=1, max_size=MAX_CLAIMS - 1, unique=True))
    score = next(f for f in evidence.facts.values() if f.name == "score")
    claims = [*reading_claims(case, evidence, chosen)]
    claims.append(Claim(f"It is {score.display}", (score.fact_id,), case.trigger_ids[-1:]))
    claims = data.draw(st.permutations(claims))
    draft = Draft(". ".join(c.text for c in claims) + ".", tuple(claims))
    verdict = check(draft, case, evidence)
    assert verdict.passed, verdict.reasons


@settings(deadline=None)
@given(st.data())
def test_a_phrase_no_cited_reading_of_its_team_shows_is_refused_and_named(data):
    case, evidence = data.draw(st.sampled_from(real_moments()))
    mine = data.draw(st.sampled_from(readings_of(evidence)))
    (claim,) = reading_claims(case, evidence, [mine])
    how = data.draw(st.sampled_from(["other phrase", "other club", "uncited"]))
    if how == "other phrase":
        phrase = data.draw(st.sampled_from(sorted(set(VOCABULARY.values()) - {mine.display})))
        claim = dataclasses.replace(claim, text=claim.text.replace(mine.display, phrase))
    elif how == "other club":
        assume(mine.team is not None)
        other = next(
            t for t in (team_names(match(int(case.match_id[1:]))).values()) if t != mine.team
        )
        claim = dataclasses.replace(
            claim, text=claim.text.replace(club_name(case, mine.team), club_name(case, other))
        )
        phrase = mine.display
    else:
        claim, phrase = dataclasses.replace(claim, fact_ids=()), mine.display
    verdict = check(Draft(claim.text + ".", (claim,)), case, evidence)
    assert not verdict.passed
    assert (ReasonCode.PHRASE_NOT_CITED, phrase) in {(r.code, r.token) for r in verdict.reasons}


@settings(deadline=None)
@given(st.data())
def test_a_phrase_outside_every_claim_is_refused_and_named(data):
    case, evidence = data.draw(st.sampled_from(real_moments()))
    phrase = data.draw(st.sampled_from(sorted(set(VOCABULARY.values()))))
    score = next(f for f in evidence.facts.values() if f.name == "score")
    claim = Claim(f"It is {score.display}", (score.fact_id,), case.trigger_ids[-1:])
    verdict = check(Draft(f"{claim.text}, so {phrase}.", (claim,)), case, evidence)
    assert (ReasonCode.PHRASE_OUTSIDE_CLAIM, phrase) in {(r.code, r.token) for r in verdict.reasons}


JUDGEMENT_WORDS = [
    "lead", "leads", "leading", "ahead", "in front", "level", "equaliser", "equalises",
    "a goal ahead",  # refused for `ahead`, as the Guard's docstring says (issue #9)
    "equalized", "opener", "winner", "comeback", "all square", "goalless", "winning", "losing",
    "advantage", "dominate", "dominating", "in control", "on the front foot", "chaotic", "calm",
    "outshoot", "outshot", "pulls one back", "pulled a goal back", "pinning back",
    "evenly-matched games", "end to end", "On Top", "an equal share of the ball",
    "more of the ball", "fewer shots", "less possession", "most of the chances",
    "more clear-cut chances", "led", "levelled", "levels", "levelling", "dominant", "dominance",
    "behind", "trailing", "trailed", "a goal down", "a goal up", "took control", "in command",
    "on the back foot", "outplayed", "superior", "Level", "draw level", "go ahead",
    "end–to–end", "end‑to‑end", "on—top",
    "beat", "beats", "beaten", "won the match", "win", "wins it", "lose", "lost to",
    "defeat", "a victory", "triumph", "a draw", "drew", "drawn",
    "beating", "loses", "draws", "defeated", "triumphed", "victorious", "won the game",
    "beat the hosts", "lost the match", "win the title", "beaten by", "win the points",
    "beat the visitors' defence", "won the loose game", "lost back the lead", "draws a draw",
    "a loss", "losses", "the losers", "drawing", "tied", "ties", "unbeaten", "unbeatable",
    "winless", "take the points", "claimed all the points", "shared the points", "see off",
    "saw off", "edge it", "edged past", "prevail", "won the possession battle",
    "lost the aerial duels", "won the tackles", "won the duels", "wins it", "won possession war",
]  # fmt: skip


@pytest.mark.parametrize("words", JUDGEMENT_WORDS)
def test_a_judgement_without_a_cited_reading_is_refused_and_named(words):
    case, evidence = _real_goal()
    good = goal_draft(case)
    verdict = check(Draft(f"{good.text} Now {words} here.", good.claims), case, evidence)
    reasons = {(r.code, (r.token or "").lower()) for r in verdict.reasons}
    found = {code for code, token in reasons if token and token in words.lower()}
    assert found & {
        ReasonCode.JUDGEMENT_WORD,
        ReasonCode.PHRASE_OUTSIDE_CLAIM,
    }, (words, verdict.reasons)


@pytest.mark.parametrize(
    "text",
    [
        "a high level of pressing", "he finishes calmly", "more than once", "the ball is loose",
        "a shot in front of goal", "ahead of the runner", "winning the ball", "losing possession",
        "the move leads to a shot", "on top of the ball", "a tackle from behind",
        "behind the defence", "a move that led to the goal", "in the lead-up",
        "takes advantage of the gap", "a calm finish", "in control of the ball", "gets in behind",
        "the move led to his goal", "a ball leading to Corrowmere's shot",
        "behind the defensive line", "ahead of him", "ahead of the runner",
        "a run at 67:23 down the right", "a run behind the visitors' defence",
        "a pass ahead of the hosts' back line", "a run behind his marker", "behind a defender",
        "he takes control of the ball", "the striker leading the line", "No. 9 up front",
        "in charge of the box", "in the lead\u2010up",
        "he beats the keeper", "he beats his marker", "he won the ball", "he wins a corner",
        "he lost the ball", "the shot draws a fine save", "he drew a foul",
        "he beats the goalkeeper", "he beats the defenders", "he beats his man",
        "the shot beats the wall", "he beats the offside trap", "they beat the press",
        "he wins possession", "he wins a free kick", "he wins a throw-in", "he wins the header",
        "he wins his duel", "he wins a tackle", "he wins the race", "he wins the flick",
        "he loses his marker", "he wins a penalty", "he wins a goal kick",
        "he won back possession", "he wins the loose ball", "he wins the second ball",
        "he won the aerial duel", "he wins an aerial duel", "it draws a block",
        "it draws a tackle", "it draws a stop", "it draws another fine save",
        "it draws an awkward save",
        "he beats the full-back", "he beats the centre-back", "he beats the defence",
        "he beats the last man", "it draws the keeper", "he draws the foul",
        "drawing a save", "he wins it back", "he loses his footing", "he won't stop",
        "the move is held up",
    ],
)  # fmt: skip
def test_words_near_a_judgement_pass(text):
    case, evidence = _real_goal()
    good = goal_draft(case)
    verdict = check(Draft(f"{good.text} Then {text}.", good.claims), case, evidence)
    codes = {r.code for r in verdict.reasons}
    assert not codes & {ReasonCode.JUDGEMENT_WORD, ReasonCode.PHRASE_OUTSIDE_CLAIM}, verdict


def test_a_cited_phrase_is_read_neither_as_a_number_nor_as_a_judgement():
    found = [
        (case, evidence, f)
        for case, evidence in real_moments()
        for f in readings_of(evidence)
        if f.display == "pull one back"
    ]
    assert found  # m0, m1 or m3 has a goal that pulls one back (counted 23 Oct)
    case, evidence, reading = found[0]
    claims = reading_claims(case, evidence, [reading])
    verdict = check(Draft(". ".join(c.text for c in claims) + ".", tuple(claims)), case, evidence)
    assert verdict.passed, verdict.reasons


def test_the_team_named_last_before_the_phrase_counts():
    case, evidence = _real_goal()
    m = match(7)
    goal = next(e for e in m.events if e.event_id == case.trigger_ids[-1])
    reading = next(f for f in readings_of(evidence) if f.name == "goal_reading")
    assert reading.team == goal.team
    other = m.meta.away if goal.team == m.meta.home else m.meta.home
    mine, theirs = club_name(case, goal.team), club_name(case, other)
    scorer = next(p.name for c in load_league().clubs for p in c.players if p.id == goal.player)

    def verdict(text: str) -> Verdict:
        claim = Claim(text, (reading.fact_id,), (goal.event_id,))
        return check(Draft(text + ".", (claim,)), case, evidence)

    phrase = reading.display
    assert verdict(f"{mine} {phrase}").passed
    assert verdict(f"{scorer} scores and {mine} {phrase}").passed
    assert verdict(f"Against {theirs}, {mine} {phrase}").passed
    assert verdict(f"{scorer} scores and they {phrase}").passed  # the scorer's club counts
    assert not verdict(f"{mine} beat {theirs} and {phrase}").passed  # the other club is last
    assert not verdict(f"They {phrase}").passed  # nobody named


@settings(deadline=None)
@given(
    st.lists(
        st.sampled_from(
            [*VOCABULARY.values(), "Vellbridge Town", "Corrowmere", "lead", "1–0", "57%", "and"]
        ),
        max_size=12,
    ),
    claims_of_anything,
)
def test_the_guard_never_raises_on_phrases_and_names(words, claims):
    case, evidence = _real_goal()
    verdict = check(Draft(" ".join(words), tuple(claims)), case, evidence)
    assert verdict.passed == (not verdict.reasons)


def test_more_or_fewer_judges_up_to_three_words_before_the_count():
    case, evidence = _real_goal()
    good = goal_draft(case)

    def judged(text: str) -> bool:
        verdict = check(Draft(f"{good.text} {text}.", good.claims), case, evidence)
        return ReasonCode.JUDGEMENT_WORD in {r.code for r in verdict.reasons}

    assert judged("More of the shots")  # capitalised, as a sentence starts
    assert judged("more clear and simple chances")  # three words between
    assert not judged("more clear and very simple chances")  # four


def test_a_reading_so_far_is_of_its_moment_s_instant_though_its_range_ends_before():
    """m7's 25th shot, its moment ending as detected 1.3 s after it: the flow so far ends at the
    last spell counted, the shot's."""
    case, evidence = moment(7, EventType.SHOT, 24, end_ms=1884726)
    chaos = evidence.facts["m7/chaos_reading/to-2-1884726/all"]
    minute = next(f for f in evidence.facts.values() if f.name == "minute")
    assert chaos.end < (case.period, case.end_ms) == minute.end
    text = f"At {minute.display} the play is {chaos.display}"
    claim = Claim(text, (minute.fact_id, chaos.fact_id), case.trigger_ids[-1:])
    assert check(Draft(f"{text}.", (claim,)), case, evidence).passed


def test_a_phrase_must_lie_wholly_inside_its_claim_on_both_sides():
    case, evidence = _real_goal()
    reading = next(f for f in readings_of(evidence) if f.name == "goal_reading")
    club = club_name(case, reading.team)
    text = f"{club} {reading.display} now."
    whole = Claim(f"{club} {reading.display}", (reading.fact_id,), case.trigger_ids[-1:])
    for cut in (whole.text[:-1], whole.text[len(club) + 2 :]):  # its end, then its start
        claim = Claim(cut, (reading.fact_id,), case.trigger_ids[-1:])
        reasons = {(r.code, r.token) for r in check(Draft(text, (claim,)), case, evidence).reasons}
        assert (ReasonCode.PHRASE_OUTSIDE_CLAIM, reading.display) in reasons, cut
    assert check(Draft(text, (whole,)), case, evidence).passed


def test_a_club_named_outside_the_claim_does_not_count_and_a_teamless_reading_needs_none():
    case, evidence = _real_goal()
    goal = next(f for f in readings_of(evidence) if f.name == "goal_reading")
    chaos = next(f for f in readings_of(evidence) if f.name == "chaos_reading")
    club = club_name(case, goal.team)
    claim = Claim(f"they {goal.display}", (goal.fact_id,), case.trigger_ids[-1:])
    verdict = check(Draft(f"{club} score and {claim.text}.", (claim,)), case, evidence)
    assert [(r.code, r.claim) for r in verdict.reasons] == [(ReasonCode.PHRASE_NOT_CITED, 0)]
    other = Claim(f"{club} play and it is {chaos.display}", (chaos.fact_id,), claim.event_ids)
    assert check(Draft(other.text + ".", (other,)), case, evidence).passed


def test_the_hint_names_the_club_of_the_reading():
    case, evidence = _real_goal()
    goal = next(f for f in readings_of(evidence) if f.name == "goal_reading")
    m = match(7)
    other = m.meta.away if goal.team == m.meta.home else m.meta.home
    text = f"{club_name(case, other)} {goal.display}"
    claim = Claim(text, (goal.fact_id,), case.trigger_ids[-1:])
    (reason,) = check(Draft(text + ".", (claim,)), case, evidence).reasons
    assert reason.code is ReasonCode.PHRASE_NOT_CITED and reason.claim == 0
    assert f"reading of {club_name(case, goal.team)}:" in reason.detail
    assert club_name(case, other) not in reason.detail


@settings(deadline=None, max_examples=50)
@given(st.data())
def test_claim_order_does_not_change_the_reasons_of_a_broken_caption(data):
    case, evidence = data.draw(st.sampled_from(real_moments()))
    chosen = data.draw(
        st.lists(st.sampled_from(readings_of(evidence)), min_size=2, max_size=6, unique=True)
    )
    claims = reading_claims(case, evidence, chosen)
    broken = data.draw(st.integers(0, len(claims) - 1))
    claims[broken] = dataclasses.replace(claims[broken], fact_ids=())  # its phrase uncited
    text = ". ".join(c.text for c in claims) + "."
    first = check(Draft(text, tuple(claims)), case, evidence)
    order = data.draw(st.permutations(claims))
    again = check(Draft(text, tuple(order)), case, evidence)
    assert not first.passed and check(Draft(text, tuple(claims)), case, evidence) == first
    assert {(r.code, r.token) for r in again.reasons} == {(r.code, r.token) for r in first.reasons}


SCORE_JUDGEMENTS = [
    "{home} extend their lead to {score}", "{away} cut the lead to {score}",
    "{home} double their lead to {score}", "{away} draw level with {home}",
    "{home} are on top of the game", "{away} come from behind", "{away} go {score} up",
    "{home} open the scoring", "{home} break the deadlock", "{away} hit back",
    "{home} restore their advantage", "{away} cancel out the goal", "{home} are the better side",
    "{away} score against the run of play", "{home} led at half time",
    "{away} are level with {home}", "{home} restore order", "{home} led to {score}",
    "{away} cut the deficit", "{away} narrow the gap", "{away} are back in the game",
    "{away} fight back", "{home} have the upper hand", "{home} are in charge",
    "{home} are the better team", "{away} are down {score}", "{away} remain behind",
    "{away} are again behind", "{away} are behind the hosts", "{away} move ahead of {home}",
    "{away} get one back", "{away} claw one back", "a {away} fightback",
    "{home} are pegged back", "{away} are the brighter side", "{away} are back on terms",
    "{away} are ahead of them", "a {away} fight-back", "a {away} come-back",
    "{away} remain behind the home side", "{away} are behind the opposition",
    "{away} are behind their rivals", "{away} are behind the visitors",
    "{away} are behind the opponents",
    "{away} are behind on the scoreboard", "{home} move ahead of the opposition",
    "{home} move ahead of the Rovers", "{away} are behind his side",
    "{away} are back on equal terms", "{home} go {score} up the moment it counts",
    "{away} got one back", "{away} grab one back", "{away} nick one back",
    "{away} snatch one back", "{home} are the stronger side", "{home} peg them right back",
    "{home} beat {away} {score}", "{away} lose {score} to {home}", "{home} win {score}",
]  # fmt: skip


@pytest.mark.parametrize("sentence", SCORE_JUDGEMENTS)
def test_a_judgement_beside_a_cited_score_is_refused(sentence):
    case, evidence = _real_goal()
    m = match(7)
    score = next(f for f in evidence.facts.values() if f.name == "score")
    text = sentence.format(
        home=club_name(case, m.meta.home), away=club_name(case, m.meta.away), score=score.display
    )
    claim = Claim(text, (score.fact_id,), case.trigger_ids[-1:])
    verdict = check(Draft(text + ".", (claim,)), case, evidence)
    codes = {r.code for r in verdict.reasons}
    assert codes & {ReasonCode.JUDGEMENT_WORD, ReasonCode.PHRASE_NOT_CITED}, (text, verdict)


@settings(deadline=None)
@given(st.data())
def test_a_reading_of_another_window_than_its_claim_is_refused(data):
    pairs = [
        (case, evidence, to, last5)
        for case, evidence in real_moments()
        for to in readings_of(evidence)
        for last5 in readings_of(evidence)
        if "/to-" in to.fact_id
        and "/last5-" in last5.fact_id
        and (to.name, to.team) == (last5.name, last5.team)
        and to.display != last5.display
    ]
    case, evidence, to, last5 = data.draw(st.sampled_from(pairs))
    who = club_name(case, to.team) + " " if to.team else "The play is "
    # the match-long reading's phrase in a claim about the last 5 minutes, both cited
    text = f"{who}{to.display} in the last 5 minutes"
    claim = Claim(text, (last5.fact_id, to.fact_id), case.trigger_ids[-1:])
    verdict = check(Draft(text + ".", (claim,)), case, evidence)
    reasons = {(r.code, r.token) for r in verdict.reasons}
    assert (ReasonCode.PHRASE_NOT_CITED, to.display) in reasons, verdict.reasons
    (why,) = [r.detail for r in verdict.reasons if r.token == to.display]
    assert "whose window is not the claim's" in why and "separate claims" in why
    # the match-long reading in a claim whose window is said in other words
    for words in (
        "recently", "in recent minutes", "in this spell", "over the last few minutes", "lately",
        "of late",
    ):  # fmt: skip
        text = f"{who}{to.display} {words}"
        claim = Claim(text, (to.fact_id,), case.trigger_ids[-1:])
        verdict = check(Draft(text + ".", (claim,)), case, evidence)
        (why,) = [r.detail for r in verdict.reasons if r.token == to.display]
        assert "'recently'" in why, words
    # a reading of the last 5 minutes may say "recently" too
    text = f"{who}{last5.display} in the last 5 minutes, recently"
    claim = Claim(text, (last5.fact_id,), case.trigger_ids[-1:])
    assert check(Draft(text + ".", (claim,)), case, evidence).passed
    # and the window's reading in a claim without the window
    text = f"{who}{last5.display}"
    claim = Claim(text, (last5.fact_id, to.fact_id), case.trigger_ids[-1:])
    verdict = check(Draft(text + ".", (claim,)), case, evidence)
    assert (ReasonCode.PHRASE_NOT_CITED, last5.display) in {
        (r.code, r.token) for r in verdict.reasons
    }


def test_a_pair_of_windows_exists_among_the_measured_moments():
    """The property above needs a moment with a reading that differs between its windows."""
    assert any(
        (to.name, to.team) == (last5.name, last5.team) and to.display != last5.display
        for _, evidence in real_moments()
        for to in readings_of(evidence)
        if "/to-" in to.fact_id
        for last5 in readings_of(evidence)
        if "/last5-" in last5.fact_id
    )


@settings(deadline=None)
@given(st.data())
def test_the_guard_never_raises_on_claims_that_cite_readings(data):
    case, evidence = data.draw(st.sampled_from(real_moments()))
    words = [*VOCABULARY.values(), *team_names(match(int(case.match_id[1:]))), "and", "5", "last"]
    words += ["in the last 5 minutes", "recently", "—", "-up"]
    text = " ".join(data.draw(st.lists(st.sampled_from(words), max_size=10)))
    readings = st.sampled_from([f.fact_id for f in readings_of(evidence)])
    claims = []
    for _ in range(data.draw(st.integers(0, 3))):
        a = data.draw(st.integers(0, len(text)))
        b = data.draw(st.integers(a, len(text)))
        fact_ids = tuple(data.draw(st.lists(readings, max_size=3)))
        claims.append(Claim(text[a:b], fact_ids, case.trigger_ids[-1:]))
    verdict = check(Draft(text, tuple(claims)), case, evidence)
    assert verdict.passed == (not verdict.reasons)


def test_a_cited_phrase_before_a_dash_is_still_the_phrase_and_a_hyphen_joins():
    case, evidence = _real_goal()
    goal = next(f for f in readings_of(evidence) if f.name == "goal_reading")
    club = club_name(case, goal.team)
    for dash in ("—", "–", " — "):
        text = f"{club} {goal.display}{dash}a cracking move"
        claim = Claim(f"{club} {goal.display}", (goal.fact_id,), case.trigger_ids[-1:])
        verdict = check(Draft(text + ".", (claim,)), case, evidence)
        assert verdict.passed, (dash, verdict.reasons)
    # a hyphen makes another word: "take the lead-in" is no phrase, its "lead" a judgement
    text = f"{club} {goal.display}-in"
    claim = Claim(text, (goal.fact_id,), case.trigger_ids[-1:])
    codes = {r.code for r in check(Draft(text + ".", (claim,)), case, evidence).reasons}
    assert ReasonCode.JUDGEMENT_WORD in codes


# the result in words, every branch and every word of its on-ball exceptions from both sides:
# (refused, passes) with the same verb
RESULT_PAIRS = [
    # beat: only a player beaten on the ball, after an article or a possessive
    ("they beat the hosts", "he beats the keeper"),
    ("they were beaten", "he beats the goalkeeper"),
    ("beating them", "he beats the defenders"),
    ("an unbeaten run", "he beats a defender"),
    ("they look unbeatable", "he beats the defence"),
    ("he beats defenders", "he beats his marker"),
    ("they beat their rivals", "he beats his man"),
    ("beat it", "he beats the last man"),
    ("beats them", "the shot beats the wall"),
    ("beats everyone", "he beats the offside trap"),
    ("beat the visitors", "they beat the press"),
    ("beat the champions", "he beats the full-back"),
    ("beat the drum", "he beats the centre-back"),
    ("they beat the team", "he beats the keeper low"),
    ("they beat the side", "he beats the keeper high"),
    ("they beat the opponents", "he beats the keeper again"),
    # win, lose: one ball, duel or tackle of one player
    ("they won", "he won the ball"),
    ("a chance to win", "he wins a corner"),
    ("he wins it", "he wins it back"),
    ("they lost to the hosts", "he lost the ball"),
    ("the side loses", "he loses his marker"),
    ("they won the match", "he wins a free kick"),
    ("they won the duels", "he wins his duel"),
    ("they won the tackles", "he wins a tackle"),
    ("they won the headers", "he wins the header"),
    ("they won the loose balls", "he wins the loose ball"),
    ("they won the second balls", "he wins the second ball"),
    ("they won the aerial duels", "he won the aerial duel"),
    ("he won ball after ball", "he wins a throw-in"),
    ("they won the possession battle", "he wins possession"),
    ("they won possession battle", "he won back possession"),
    ("they won possession war", "he wins a foul"),
    ("they won possession game", "he wins the race"),
    ("they won possession contest", "he wins the flick"),
    ("they won possession stakes", "he wins a penalty"),
    ("they won the penalty shoot-out", "he wins a goal kick"),
    ("they lost back the lead", "he loses his footing"),
    ("they won the title", "he won't stop"),
    # the result's nouns and verbs: no exception
    ("a loss", "a loose ball"),
    ("heavy losses", "he loses his marker"),
    ("the loser", "he lost the ball"),
    ("the losers", "he wins the race"),
    ("a winless run", "he wins a corner"),
    ("a defeat", "he defends deep"),
    ("they were defeated", "he defends the box"),
    ("a victory", "a shot from the left"),
    ("a victorious side", "a shot from the right"),
    ("a triumph", "a shot from the centre"),
    ("a stalemate", "a shot from distance"),
    ("they overcame the hosts", "he comes over to help"),
    ("they overcome the hosts", "he comes back to help"),
    ("they prevail", "he previews the pass"),
    # tie: only "tied up"
    ("a tie", "the move is held up"),
    ("they tie", "they hold up the move"),
    ("the ties", "the ball is held up"),
    ("the sides are tied", "the play is held up"),
    ("the sides were tied in the second half", "he is held up"),
    ("they tied down the match", "the winger is held up"),
    ("he ties his marker", "the move gets held up"),
    # draw: only what a shot or a run draws
    ("a draw", "the shot draws a fine save"),
    ("it ends in a draw", "he drew a foul"),
    ("they drew", "it draws a block"),
    ("it was drawn", "it draws a tackle"),
    ("they are drawing", "it draws a stop"),
    ("drawing level", "drawing a save"),
    ("they draw", "it draws another fine save"),
    ("they draw it", "it draws an awkward save"),
    ("a match drawn", "it draws the keeper"),
    ("draw the match", "it draws the goalkeeper"),
    ("draws a draw", "he draws the foul"),
    ("they draw a game with no save", "it draws a sharp save"),
    # the points
    ("they take the points", "he takes the ball"),
    ("she takes the points", "he takes the corner"),
    ("they took the points", "he took the free kick"),
    ("taking the points", "taking the throw-in"),
    ("they claimed all the points", "he claims the ball"),
    ("they shared the points", "he shares the ball"),
    ("they collect the points", "he collects the ball"),
    ("they bank the points", "a shot from the bank"),
    # see off, edge
    ("they see off the hosts", "he sees the shot"),
    ("she sees off the hosts", "he sees a gap"),
    ("they saw off the hosts", "he saw the run"),
    ("they have seen off the hosts", "he has seen the run"),
    ("they see them off", "he sees the keeper off his line"),
    ("they edge it", "the edge of the box"),
    ("they edges it", "from the edge of the area"),
    ("they edged past the hosts", "on the edge of the area"),
    ("they edge out the hosts", "the edge of the six-yard box"),
    # round 3 of item 4: the listed words in every form
    ("they are tying the game", "the move stalls"),
    ("the match finished all tied up", "the winger is held up again"),
    ("they are overcoming the hosts", "he comes over again"),
    ("they overcomes the hosts", "he comes over to block"),
    ("they prevailed", "he previews the cross"),
    ("they prevails", "he previews the run"),
    ("two stalemates", "a shot at the far post"),
    ("they are seeing off the hosts", "he is seeing the gap"),
    ("they are edging past the hosts", "he is near the edge of the box"),
    ("they are edging it", "he is on the edge of the box"),
    ("the sides are sharing the points", "he is sharing the ball"),
    ("they have taken the points", "he has taken the ball"),
    ("they take points", "he takes the free kick"),
    ("they secured the points", "he secured the ball"),
    ("they earned all the points", "he earned a corner"),
    ("they grabbed a point", "he grabbed the ball"),
    ("they pocketed the points", "he pocketed the ball"),
    ("they pick up a point", "he picks up the ball"),
    ("they walked away with the points", "he walked away from the ball"),
    ("they walked off with both points", "he walked off the pitch"),
    ("they took a point", "he took a corner"),
    ("they won", "he won’t stop"),
    ("they beat her rivals", "he beats her marker"),
    ("they beat their rivals", "he beats their keeper"),
    ("they are winning", "he is winning the ball"),
    ("they are winning the duels", "he is winning his duel"),
    ("they are winning the possession battle", "he is winning possession"),
    ("they are losing", "he is losing possession"),
    ("they are losing the tackles", "he is losing his marker"),
    # round 4 of item 4: derived forms, every "points", the verb "edge", "see ... off"
    ("they are stalemating the hosts", "he stays wide"),
    ("it stalemated", "he stayed wide"),
    ("they stay undefeated", "he defends well"),
    ("they look undefeatable", "he defends the far post"),
    ("a winnable game", "a headed chance"),
    ("an unwinnable game", "a long pass"),
    ("an unwon game", "he wins the header"),
    ("their winnings", "he wins the flick"),
    ("the winningest side", "he wins the race"),
    ("they outwon the hosts", "he went outside"),
    ("they out-win the hosts", "he goes outside"),
    ("two beatings", "he beats the keeper"),
    ("unbeatably good", "he beats the wall"),
    ("a losable game", "he loses his marker"),
    ("the losings", "he loses his footing"),
    ("a redraw", "it draws a save"),
    ("they re-drew", "he drew a foul"),
    ("drawings", "it draws a block"),
    ("a retie", "the move is held up"),
    ("they retied", "the run is held up"),
    ("the points were shared", "at this point"),
    ("points shared", "a point-blank save"),
    ("their points", "from point-blank range"),
    ("maximum points", "a point‑blank finish"),
    ("they picked up the points", "he picked up the ball"),
    ("they collected the points", "he collected the ball"),
    ("they banked the points", "he banked the shot in"),
    ("a point was earned", "at this point he passes"),
    ("they won possession battles", "he wins possession"),
    ("they saw the hosts off", "he saw the ball"),
    ("they saw the visiting side off", "he saw the gap open"),
    ("a see-off", "he sees the run"),
    ("they see the hosts off the pitch", "he sees the keeper off the line"),
    ("they saw them off", "he saw their keeper off his line"),
    ("they see the champions off", "she sees the keeper off her line"),
    ("they saw the leaders off", "they see the keeper off their line"),
    ("they edge the hosts", "the edge of the box"),
    ("they edged them out", "the edges of the box"),
    ("they edge it late", "at the edge of the area"),
    ("they won possession-battles", "he wins a free-kick"),
    ("they outwin the hosts", "he wins a free‑kick"),
    # second review of item 4: the noun edge, a point after words, a number after an exception
    ("they had the edge", "the edge of the box"),
    ("they hold an edge", "an edge of the area"),
    ("on the edge", "on the edge of the box"),
    ("they earned a deserved point", "a point-blank save"),
    ("a hard-earned point", "a point‑blank header"),
    ("they won possession 58% to 42%", "he wins possession again"),
    ("they won the duel 3–2", "he won the duel again"),
    ("they beat the keeper 3–2", "he beats the keeper again"),
    ("they beat the press 3–2", "they beat the press again"),
    ("they won it back 3–2", "he won it back again"),
    ("they wins it back 3–2", "he wins it back"),
    ("they drew a save 3–2", "he drew a save"),
    ("they draw a fine save 3–2", "it draws a fine save"),
    # round 7 of item 4: point after any word, edge only of a place, see-them-off
    ("they earned an important point", "at this point"),
    ("they took another point", "at that point"),
    ("their point", "at that point again"),
    ("the single point", "a point-blank save"),
    ("a point", "from point‑blank range"),
    ("they had the edge of the contest", "the edge of the box"),
    ("the edge of the game", "the edge of the penalty area"),
    ("the edge of the match", "the edge of the pitch"),
    ("on the edge of victory", "the edge of the D"),
    ("they see-them-off", "he sees the keeper off his line"),
    # round 8 of item 4: only "at this point", "at that point" and point-blank pass
    ("they earned this point", "at this point he shoots"),
    ("they took that point", "at that point he shoots"),
    ("they took a point of", "a point blank finish"),
    ("they take points of the day", "a point-blank header"),
    ("the point of the match", "at this point"),
    ("from this point on", "at that point"),
    ("they saw the hosts' attack off", "he saw the hosts' attack"),
    ("they see the visitors’ threat off", "he sees the visitors’ keeper off his line"),
    ("at this points", "at this point he crosses"),
    ("points blank", "point blank"),
]  # fmt: skip


@pytest.mark.parametrize(("refused", "passes"), RESULT_PAIRS)
def test_the_result_in_words_is_refused_and_its_on_ball_neighbour_passes(refused, passes):
    case, evidence = _real_goal()
    good = goal_draft(case)

    def judged(text: str) -> bool:
        verdict = check(Draft(f"{good.text} Then {text}.", good.claims), case, evidence)
        return ReasonCode.JUDGEMENT_WORD in {r.code for r in verdict.reasons}

    assert judged(refused), refused
    assert not judged(passes), passes

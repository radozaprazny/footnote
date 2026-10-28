"""Slovak: the Guard's rules in a second language, the Translator behind it, and the translations'
way through the state, the log, the summary, the CLI and the replay."""

import asyncio
import dataclasses
import functools
import json
import re
from collections import Counter

import pytest
from explain_strategies import REJECT
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from real import (
    cli_on_v1,  # noqa: F401 (autouse: the CLI replays on v1)
    match,
)

from matchlens import cli
from matchlens.events import EventType, display_clock
from matchlens.explain import translator
from matchlens.explain.analyst import DRAFT_SCHEMA, moment_prompt
from matchlens.explain.fake import SCORE_SK, FakeChatClient, by_moment, echo
from matchlens.explain.fulltime import fallback_recap, recap_case
from matchlens.explain.guard import (
    MAX_TEXT,
    RECAP_MAX_TEXT,
    TRANSLATION_SLACK,
    check,
    judge,
    moment_evidence,
    numerals,
    recap_evidence,
    stats_only_draft,
    team_names,
)
from matchlens.explain.log import Handoff, HandoffLog, Role, read_handoffs
from matchlens.explain.state import (
    ANALYST,
    TRANSLATION_ATTEMPTS,
    Attempt,
    CallError,
    CallFailure,
    Claim,
    Draft,
    Lang,
    MomentCase,
    Persona,
    ReasonCode,
    RenditionOutcome,
    Translation,
    Verdict,
)
from matchlens.explain.summary import check_chain, summarize
from matchlens.explain.translator import Translator, translate, translation_prompt
from matchlens.facts import facts_at, match_facts
from matchlens.league import load_league
from matchlens.render.moments import match_overlay, moment_cues
from matchlens.render.recap import closing, match_recap
from matchlens.stats.readings import PHRASES, VOCABULARY, VOCABULARY_SK

SK = Lang.SK.value
WINDOWS = {"en": " in the last 5 minutes", SK: " za posledných 5 minút"}
PLAY = {"en": "The play is", SK: "Hra je"}  # before a reading of no team
IT_IS = {"en": "It is", SK: "Stav je"}


def moment(seed: int, kind: EventType = EventType.GOAL, nth: int = 0) -> MomentCase:
    m = match(seed)
    e = [e for e in m.events if e.type is kind][nth]
    return MomentCase(
        run_id="r1",
        match_id=m.meta.match_id,
        moment_id=f"{m.meta.match_id}-k{nth}",
        trigger_ids=(e.related, e.event_id) if e.related else (e.event_id,),
        period=e.period,
        start_ms=max(0, e.clock_ms - 10_000),
        end_ms=e.clock_ms,
        display_clock=display_clock(e.period, e.clock_ms),
        facts=tuple(f.to_dict() for f in facts_at(m, e.period, e.clock_ms)),
    )


@functools.cache
def real_moments() -> list:
    """Every goal and save of the matches of the measured runs, with its evidence."""
    found = []
    for seed in (0, 1, 3):
        m = match(seed)
        for kind in (EventType.GOAL, EventType.SAVE):
            for nth in range(sum(e.type is kind for e in m.events)):
                case = moment(seed, kind, nth)
                found.append((case, moment_evidence(m, case)))
    return found


@functools.cache
def goal() -> tuple:
    case = moment(7)
    return case, moment_evidence(match(7), case)


def fact(evidence, name: str, team: str | None = None, scope: str = "to"):
    return next(
        f
        for f in evidence.facts.values()
        if f.name == name and f.team == team and f.fact_id.split("/")[2].startswith(scope)
    )


def club_name(team: str) -> str:
    return next(c.name for c in load_league().clubs if c.id == team)


def caption(case, evidence, readings, lang: str, *, outside: str = "") -> Draft:
    """A claim per reading (its club, its phrase in `lang`, its window), then the score."""
    claims = []
    for f in readings:
        who = club_name(f.team) if f.team else PLAY[lang]
        window = WINDOWS[lang] if "/last5-" in f.fact_id else ""
        text = f"{who} {PHRASES[lang][f.value]}{window}"
        claims.append(Claim(text, (f.fact_id,), case.trigger_ids[-1:]))
    score = fact(evidence, "score")
    claims.append(Claim(f"{IT_IS[lang]} {score.display}", (score.fact_id,), case.trigger_ids[-1:]))
    return Draft(". ".join(c.text for c in claims) + "." + outside, tuple(claims))


def codes(verdict: Verdict) -> set[ReasonCode]:
    return {r.code for r in verdict.reasons}


def readings_of(evidence) -> list:
    return sorted(
        (f for f in evidence.facts.values() if f.name.endswith("_reading")),
        key=lambda f: f.fact_id,
    )


# --- the vocabulary ----------------------------------------------------------------------------


def test_every_reading_has_one_slovak_phrase_the_guard_finds_whole():
    assert VOCABULARY_SK.keys() == VOCABULARY.keys() and PHRASES == {
        "en": VOCABULARY,
        SK: VOCABULARY_SK,
    }
    phrases = list(VOCABULARY_SK.values())
    assert len(set(phrases)) == len(phrases)
    pattern = translator.LANGUAGES[SK].phrase
    for phrase in phrases:
        assert not re.search(r"\d", phrase) and phrase == phrase.lower()
        assert [m.group() for m in pattern.finditer(f"x {phrase} x")] == [phrase]
        # no Slovak phrase is a number word (judgement words it may hold: the Guard blanks every
        # phrase before it reads them, and a cited phrase passes, as the properties below show)
        assert not translator.LANGUAGES[SK].number_words.search(phrase), phrase


# --- the properties: one rule set in both languages, every numeral kept ---------------------------


@settings(deadline=None)
@given(st.data())
def test_a_caption_of_cited_readings_passes_in_both_languages(data):
    case, evidence = data.draw(st.sampled_from(real_moments()))
    readings = st.sampled_from(readings_of(evidence))
    chosen = data.draw(st.lists(readings, min_size=1, max_size=6, unique=True))
    for lang in ("en", SK):
        draft = caption(case, evidence, chosen, lang)
        verdict = check(draft, case, evidence, lang)
        assert verdict.passed, (lang, draft.text, verdict.reasons)


BREACHES = {  # each way to break a caption, and the reason it must get in either language
    "other phrase": ReasonCode.PHRASE_NOT_CITED,
    "other club": ReasonCode.PHRASE_NOT_CITED,
    "uncited": ReasonCode.PHRASE_NOT_CITED,
    "outside": ReasonCode.PHRASE_OUTSIDE_CLAIM,
    "window": ReasonCode.PHRASE_NOT_CITED,
    "number word": ReasonCode.NUMBER_WORD,
    "judgement": ReasonCode.JUDGEMENT_WORD,
    "numeral": ReasonCode.NUMBER_OUTSIDE_CLAIM,
}
BREACH_WORDS = {
    "number word": {"en": " Two shots.", SK: " Dve strely."},
    "judgement": {"en": " They lead.", SK: " Vedú."},
    "numeral": {"en": " 98 passes.", SK: " 98 prihrávok."},
}


@settings(deadline=None)
@given(st.data(), st.sampled_from(sorted(BREACHES)))
def test_the_guard_s_rules_hold_in_both_languages_on_the_same_facts(data, breach):
    """The same caption in English and in Slovak, broken the same way, gets the same reasons,
    the breach's own among them."""
    case, evidence = data.draw(st.sampled_from(real_moments()))
    mine = data.draw(st.sampled_from(readings_of(evidence)))
    other_code = data.draw(st.sampled_from(sorted(set(VOCABULARY) - {mine.value})))
    teams = team_names(match(int(case.match_id[1:])))
    other_team = next(t for t in set(teams.values()) if t != mine.team)
    if breach == "other club":
        assume(mine.team is not None)
    found = {}
    for lang in ("en", SK):
        draft = caption(case, evidence, [mine], lang)
        claim, score = draft.claims
        phrase = PHRASES[lang][mine.value]
        if breach == "other phrase":
            claim = dataclasses.replace(
                claim, text=claim.text.replace(phrase, PHRASES[lang][other_code])
            )
        elif breach == "other club":
            name = club_name(other_team)
            claim = dataclasses.replace(claim, text=claim.text.replace(club_name(mine.team), name))
        elif breach == "uncited":
            claim = dataclasses.replace(claim, fact_ids=())
        elif breach == "window":
            window = WINDOWS[lang]
            text = claim.text.replace(window, "") if window in claim.text else claim.text + window
            claim = dataclasses.replace(claim, text=text)
        draft = Draft(f"{claim.text}. {score.text}.", (claim, score))
        if breach == "outside":
            draft = Draft(f"{score.text}, {phrase}.", (score,))
        elif breach in BREACH_WORDS:
            draft = Draft(draft.text + BREACH_WORDS[breach][lang], draft.claims)
        verdict = check(draft, case, evidence, lang)
        assert BREACHES[breach] in codes(verdict), (lang, draft.text, verdict.reasons)
        found[lang] = codes(verdict)
    assert found["en"] == found[SK], (breach, found)


def _mutations(text: str) -> list[tuple[str, str]]:
    """(what, text) for each way to change one numeral of `text` and nothing else."""
    found = []
    numeral = r"[0-9]+\+[0-9]+'|[0-9]+:[0-9]{2}|[0-9]+–[0-9]+|[0-9]+'|[0-9]+(?:\.[0-9]+)?%?"
    for m in re.finditer(numeral, text):
        token, a, b = m.group(), m.start(), m.end()
        found.append(("dropped", text[:a] + text[b:]))
        found.append(("doubled", text[:b] + " " + token + text[b:]))
        if token.endswith("%"):
            found.append(("spaced", text[:a] + token[:-1] + " %" + text[b:]))
        if "." in token:
            found.append(("comma", text[:a] + token.replace(".", ",") + text[b:]))
        if "–" in token:
            found.append(("hyphen", text[:a] + token.replace("–", "-") + text[b:]))
        if token.endswith("'"):  # 68. minúta
            found.append(("ordinal", text[:a] + token[:-1] + "." + text[b:]))
        if ":" in token:
            found.append(("dotted", text[:a] + token.replace(":", ".") + text[b:]))
    return found


@settings(deadline=None)
@given(st.data())
def test_no_numeral_differs_between_a_text_and_its_translation(data):
    """A translation that keeps its source's numerals byte for byte passes; one that changes,
    drops or adds any of them is refused, naming the numeral. Numerals of every kind a moment
    has: a score, a percentage, the window's minutes, a clock and a minute."""
    case, evidence = data.draw(st.sampled_from(real_moments()))
    readings = data.draw(st.lists(st.sampled_from(readings_of(evidence)), max_size=3, unique=True))
    source = caption(case, evidence, readings, "en")
    translation = caption(case, evidence, readings, SK)
    said = {  # a fact name: how a claim says its display in English and in Slovak
        "possession": ("possession is {}", "držanie lopty je {}"),
        "clock": ("the clock shows {}", "hodiny ukazujú {}"),
        "minute": ("the minute is {}", "minúta je {}"),
    }
    for name, (en_text, sk_text) in said.items():
        f = next(f for f in evidence.facts.values() if f.name == name)
        en = Claim(en_text.format(f.display), (f.fact_id,), case.trigger_ids[-1:])
        sk = Claim(sk_text.format(f.display), (f.fact_id,), case.trigger_ids[-1:])
        source = Draft(f"{source.text} {en.text}.", (*source.claims, en))
        translation = Draft(f"{translation.text} {sk.text}.", (*translation.claims, sk))
    assert check(source, case, evidence).passed
    assert check(translation, case, evidence, SK, source).passed
    assert Counter(numerals(source.text)) == Counter(numerals(translation.text))
    what, text = data.draw(st.sampled_from(_mutations(translation.text)))
    changed = Draft(text, translation.claims)
    verdict = check(changed, case, evidence, SK, source)
    assert ReasonCode.NUMERAL_CHANGED in codes(verdict), (what, text, verdict.reasons)
    # without the source, only what the Guard reads anyway: a dropped numeral may pass
    if what == "dropped":
        assert ReasonCode.NUMERAL_CHANGED not in codes(check(changed, case, evidence, SK))


# --- the Slovak rules, pinned from both sides -------------------------------------------------

SK_NUMBER_WORDS = [
    "nula", "nulou", "jeden", "jedna", "jedného", "jednom", "dva", "dve", "dvoch", "tri",
    "troch", "štyri", "päť", "šesť", "desať", "jedenásť", "dvadsať", "päťdesiat", "sto",
    "dvakrát", "trikrát", "päťkrát", "prvý", "prvá", "prvého", "druhý", "druhom", "druhej",
    "tretí", "štvrtý", "piaty", "polovica", "polovicu", "polovičný", "pol", "pár", "len raz",
    "iba raz", "hetrik", "dvojnásobný", "dvojica", "jednu", "prvú", "druhú", "štvrtú", "piatu",
    "dvaja", "traja", "štyria", "piati", "piatich", "tretíkrát", "štvrtýkrát", "piatykrát",
    "jedenkrát", "zdvojnásobil",
]  # fmt: skip
SK_NOT_NUMBERS = [
    "druh hry", "jedenástka", "strela z prvej", "jeden na jedného", "štvrtý rozhodca",
    "v prvom rade", "prvý dotyk", "tribúna", "dvere", "miesto", "páru", "raz", "Tristan",
    "z prvej a rýchlo", "center na druhú žrď", "prenáša hru na druhú stranu", "druhú loptu",
    "v druhom polčase", "na druhej strane", "na vlastnej polovici", "o pár sekúnd neskôr",
    "z prvej prihráva", "z prvej strelil",
]  # fmt: skip


def test_z_prvej_is_a_first_time_shot_only_before_no_counted_noun():
    case, evidence = goal()
    good = caption(case, evidence, [], SK)
    for words, passes in (("skóroval z prvej", True), ("skóroval z prvej strely", False),
                          ("z prvej šance", False), ("z prvej minúty", False),
                          ("z prvej vyloženej šance", False),
                          ("z prvej presnej nízkej strely", False)):  # fmt: skip
        verdict = check(Draft(f"{good.text} Teraz {words}.", good.claims), case, evidence, SK)
        assert verdict.passed == passes, (words, verdict.reasons)
        assert passes or (ReasonCode.NUMBER_WORD, "prvej") in {
            (r.code, r.token) for r in verdict.reasons
        }


@pytest.mark.parametrize("word", SK_NUMBER_WORDS)
def test_a_slovak_number_in_words_is_refused(word):
    case, evidence = goal()
    good = caption(case, evidence, [], SK)
    verdict = check(Draft(f"{good.text} Je to {word} strela.", good.claims), case, evidence, SK)
    assert (ReasonCode.NUMBER_WORD, word) in {(r.code, r.token) for r in verdict.reasons}


@pytest.mark.parametrize("words", SK_NOT_NUMBERS)
def test_slovak_words_that_only_look_like_numbers_pass(words):
    case, evidence = goal()
    good = caption(case, evidence, [], SK)
    verdict = check(Draft(f"{good.text} A {words}.", good.claims), case, evidence, SK)
    assert ReasonCode.NUMBER_WORD not in codes(verdict), verdict.reasons


SK_JUDGEMENTS = [
    "vedie", "vedú", "viedol", "vedenie", "vedenia", "vyrovnal", "vyrovnanie", "vyrovnaná hra",
    "náskok", "znížil", "znižujú", "remíza", "nerozhodne", "vyhrali", "výhra", "víťazstvo",
    "prehráva", "prehra", "porazili", "porážka", "zdolali", "dominuje", "pod kontrolou",
    "chaotická", "viac striel", "menej prihrávok", "najviac šancí", "viac z držania lopty",
    "vyhráva súboj", "vyhráva súboj s nimi",
    # a reading's phrase in another form than the one it cites
    "je navrchu", "naháňajú skóre", "naháňal skóre", "k vedeniu", "znižovali", "otvorenú hru",
    "hra je otvorená", "trpezlivú rozohrávku", "rovnomerným tempom", "väčší podiel lopty",
    "rovnakým podielom lopty", "pod veľkým tlakom",
]  # fmt: skip
SK_NOT_JUDGEMENTS = ["vedie k strele", "vedie loptu", "vyhrá loptu", "vyhráva súboj o loptu",
                     "vyhrá hlavičkový súboj", "pokojne zakončil", "naháňa loptu",
                     "viac hráčov", "menej času", "pokojne premieňa", "obratne obišiel obrancu",
                     "obratný brankár", "zostáva vzadu", "kontroluje hráča",
                     "kontroluje loptu hruďou", "našiel otvoreného hráča",
                     "podiel držania lopty", "útok vedený po pravej strane",
                     "vedenie lopty"]  # fmt: skip
# an English judgement word and its Slovak: both refused, each by its language's list
JUDGEMENT_PAIRS = [
    ("opens the scoring", "otvoril skóre"), ("opener", "úvodný gól"), ("trailing", "zaostáva"),
    ("behind", "je vzadu"), ("comeback", "obrat"), ("goalless", "bezgólový"),
    ("the points", "body"), ("superior", "prevaha"), ("in control", "kontroluje hru"),
    ("better side", "lepší tím"), ("calm", "pokojný"), ("lead", "vedie"),
    ("equaliser", "vyrovnanie"), ("a draw", "remíza"), ("won", "vyhrali"),
    ("victory", "víťazstvo"), ("lost", "prehrali"), ("defeat", "porážka"), ("beat", "porazili"),
    ("dominate", "dominujú"), ("chaotic", "chaotická"), ("more shots", "viac striel"),
    ("share of the ball", "väčší podiel lopty"), ("unbeaten", "neporazený"),
    ("undefeated", "neprehrali"), ("winless", "nevyhrali"), ("drew", "remizovali"),
    ("drawn", "zremizovali"), ("tied", "nezremizovali"),
    ("won the match", "zvíťazili"), ("opens the scoring", "otvára skóre"),
    ("took control", "kontroloval hru"), ("behind", "je stále vzadu"),
    ("won ball after ball", "vyhráva loptu za loptou"),
]  # fmt: skip


@pytest.mark.parametrize(("en", "sk"), JUDGEMENT_PAIRS)
def test_an_english_judgement_word_and_its_slovak_are_both_refused(en, sk):
    case, evidence = goal()
    for lang, words in (("en", en), (SK, sk)):
        good = caption(case, evidence, [], lang)
        text = f"{good.text} {'Now' if lang == 'en' else 'Teraz'} {words}."
        verdict = check(Draft(text, good.claims), case, evidence, lang)
        assert ReasonCode.JUDGEMENT_WORD in codes(verdict), (lang, words, verdict.reasons)


@pytest.mark.parametrize("words", SK_JUDGEMENTS)
def test_a_slovak_judgement_without_a_cited_reading_is_refused(words):
    case, evidence = goal()
    good = caption(case, evidence, [], SK)
    verdict = check(Draft(f"{good.text} Teraz {words}.", good.claims), case, evidence, SK)
    tokens = [r.token for r in verdict.reasons if r.code is ReasonCode.JUDGEMENT_WORD]
    assert tokens and all(t.lower() in words for t in tokens), verdict.reasons


@pytest.mark.parametrize("words", SK_NOT_JUDGEMENTS)
def test_slovak_words_near_a_judgement_pass(words):
    case, evidence = goal()
    good = caption(case, evidence, [], SK)
    verdict = check(Draft(f"{good.text} Teraz {words}.", good.claims), case, evidence, SK)
    assert verdict.passed, verdict.reasons


def test_the_english_lists_judge_no_slovak_text_and_the_slovak_ones_no_english():
    case, evidence = goal()
    good = caption(case, evidence, [], SK)
    # Slovak "ten" (that) and "tie" (those) are English number and judgement words
    assert check(
        Draft(f"{good.text} Ten hráč a tie strely.", good.claims), case, evidence, SK
    ).passed
    en = caption(case, evidence, [], "en")
    assert check(Draft(f"{en.text} Vedie the line.", en.claims), case, evidence).passed


def test_a_slovak_claim_of_the_last_five_minutes_names_them_in_slovak():
    case, evidence, last5 = next(
        (c, e, f)
        for c, e in real_moments()
        for f in e.facts.values()
        if "/last5-" in f.fact_id and f.name == "momentum"
    )
    who = club_name(last5.team)
    trigger = case.trigger_ids[-1:]
    for window, passes in (
        ("za posledných 5 minút", True),
        ("v posledných 5 minútach", True),
        ("za ostatných päť minút", True),
        ("za posledných 6 minút", False),
        ("in the last 5 minutes", False),
        ("", False),
    ):
        claim = Claim(f"{who} má {last5.display} {window}".strip(), (last5.fact_id,), trigger)
        verdict = check(Draft(claim.text + ".", (claim,)), case, evidence, SK)
        assert verdict.passed == passes, (window, verdict.reasons)
        assert passes or ReasonCode.SCOPE_NOT_NAMED in codes(verdict), verdict.reasons


def test_a_slovak_reading_beside_other_words_for_a_time_is_refused():
    case, evidence = goal()
    mine = next(f for f in readings_of(evidence) if "/last5-" not in f.fact_id and f.team)
    (claim, score) = caption(case, evidence, [mine], SK).claims
    for words in ("", " nedávno", " v tejto fáze", " v poslednom čase", " v druhom polčase",
                  " cez polčas", " po prestávke", " pred prestávkou",
                  " za posledných niekoľko minút"):  # fmt: skip
        text = claim.text + words
        changed = dataclasses.replace(claim, text=text)
        verdict = check(Draft(f"{text}. {score.text}.", (changed, score)), case, evidence, SK)
        assert verdict.passed == (not words), (words, verdict.reasons)
        assert (ReasonCode.PHRASE_NOT_CITED in codes(verdict)) == bool(words), verdict.reasons


def test_a_slovak_shirt_number_needs_its_context():
    case, evidence = goal()
    m = match(7)
    scorer = next(e for e in m.events if e.event_id == case.trigger_ids[-1]).player
    shirt = next(
        f for f in evidence.facts.values() if f.name == "shirt_number" and f.player == scorer
    )
    trigger = case.trigger_ids[-1:]
    for before, after, passes in (
        ("č. ", "", True),
        ("číslo ", "", True),
        ("#", "", True),
        ("s dresom ", "", True),
        ("", " na drese", True),
        ("", "", False),
        ("", " na ihrisku", False),
    ):
        claim = Claim(f"hráč {before}{shirt.display}{after}", (shirt.fact_id,), trigger)
        verdict = check(Draft(claim.text + ".", (claim,)), case, evidence, SK)
        assert verdict.passed == passes, (before, after, verdict.reasons)


def test_a_translation_keeps_the_source_s_names():
    case, evidence = goal()
    name = "Adrien Pellacourt"
    source = caption(case, evidence, [], "en")
    source = Draft(f"{name} scores. {source.text}", source.claims)
    good = caption(case, evidence, [], SK)
    changed, unknown = ReasonCode.NAME_CHANGED, ReasonCode.UNKNOWN_NAME
    for text, found in (
        (f"{name} skóruje. {good.text}", set()),
        (f"Skóruje. {good.text}", {(changed, "Adrien"), (changed, "Pellacourt")}),
        (f"{name} a Tomasz Wierlo. {good.text}", {(changed, "Tomasz"), (changed, "Wierlo")}),
        (f"Adrien Pellacourta. {good.text}", {(changed, "Pellacourt"), (unknown, "Pellacourta")}),
    ):  # fmt: skip
        verdict = check(Draft(text, good.claims), case, evidence, SK, source)
        assert {(r.code, r.token) for r in verdict.reasons} == found, text


def test_a_translation_keeps_each_numeral_as_often_as_the_source():
    case, evidence = goal()
    score = fact(evidence, "score")
    source = caption(case, evidence, [], "en")
    once = caption(case, evidence, [], SK)
    twice = Draft(f"{once.text} {once.claims[0].text}.", once.claims)
    assert check(once, case, evidence, SK, source).passed
    verdict = check(twice, case, evidence, SK, source)
    assert [(r.code, r.token) for r in verdict.reasons] == [
        (ReasonCode.NUMERAL_CHANGED, score.display)
    ]
    source_twice = Draft(f"{source.text} {source.claims[0].text}.", source.claims)
    assert check(twice, case, evidence, SK, source_twice).passed
    assert not check(once, case, evidence, SK, source_twice).passed


@pytest.mark.parametrize("recap", [False, True])
def test_a_translation_may_run_a_quarter_longer_than_its_source_s_limit(recap):
    case, evidence = goal()
    if recap:
        whole = match_facts(match(7))
        case = recap_case(match(7), "r1", whole)
        evidence = recap_evidence(match(7), case, whole)
    good = (
        fallback_recap(match(7), case, evidence, SK) if recap else caption(case, evidence, [], SK)
    )
    limit = RECAP_MAX_TEXT if recap else MAX_TEXT
    longest = int(limit * TRANSLATION_SLACK)

    def padded(length: int) -> Draft:
        return Draft(good.text + " " + "a" * (length - len(good.text) - 1), good.claims)

    assert len(padded(longest).text) == longest
    assert check(padded(longest), case, evidence, SK, good).passed
    assert codes(check(padded(longest + 1), case, evidence, SK, good)) == {ReasonCode.TOO_LONG}
    assert codes(check(padded(limit + 1), case, evidence, SK)) == {ReasonCode.TOO_LONG}
    assert check(padded(limit), case, evidence, SK).passed


def test_every_real_moment_s_slovak_stats_only_cue_passes_with_the_english_numerals():
    for case, evidence in real_moments():
        sk, en = stats_only_draft(case, evidence, SK), stats_only_draft(case, evidence)
        assert check(sk, case, evidence, SK, en).passed, sk
        assert sk.text != en.text and [c.fact_ids for c in sk.claims] == [
            c.fact_ids for c in en.claims
        ]
        assert sk.text.startswith("minúta ")


@pytest.mark.parametrize("seed", [0, 1, 3, 7])
def test_the_slovak_deterministic_recap_passes_with_the_english_numerals(seed):
    m = match(seed)
    whole = match_facts(m)
    case = recap_case(m, "r1", whole)
    evidence = recap_evidence(m, case, whole)
    sk, en = fallback_recap(m, case, evidence, SK), fallback_recap(m, case, evidence)
    assert check(sk, case, evidence, SK, en).passed, (sk.text, check(sk, case, evidence, SK, en))
    assert sk.text.startswith("Konečný výsledok ") and en.text.endswith(".")
    assert [c.fact_ids for c in sk.claims] == [c.fact_ids for c in en.claims]


def test_the_scorers_sentence_agrees_with_their_number():
    m = match(7)
    whole = match_facts(m)
    case = recap_case(m, "r1", whole)
    evidence = recap_evidence(m, case, whole)
    one = dataclasses.replace(case, trigger_ids=case.trigger_ids[:2])
    assert "Skórovali " in fallback_recap(m, case, evidence, SK).text
    assert "Skóroval " in fallback_recap(m, one, evidence, SK).text


# --- the state ----------------------------------------------------------------------------------


def narrative(seed: int = 7, fan: str | None = "own") -> MomentCase:
    """A real goal whose `--fake` draft passed, with a fan rendition: its own draft that passed
    (`own`), fallen back (`fallback`) or none (None)."""
    m = match(seed)
    case = moment(seed)
    draft = Draft.from_dict(json.loads(echo(moment_prompt(case, m))))
    case = case.with_attempt(Attempt(1, "fake", draft))
    case = case.with_verdict(judge(case, moment_evidence(m, case)))
    if fan is None:
        return case
    case = case.with_personas([Persona.FAN])
    r = case.renditions[0]
    if fan == "own":
        own = Draft(draft.text.replace("The score", "Now the score"), draft.claims)
        own = Draft(own.text, (dataclasses.replace(own.claims[0], text=own.text[:-1]),))
        r = r.with_attempt(Attempt(1, "fake", own))
        r = r.with_verdict(judge(case.with_rendition(r), moment_evidence(m, case)))
        assert r.outcome is RenditionOutcome.PASSED
    else:
        r = r.fallback()
    return case.with_rendition(r)


def test_translations_come_of_a_closed_narrative_and_each_own_text_once():
    case = narrative()
    assert [(t.lang, t.persona) for t in case.with_translations(["sk", "sk"]).translations] == [
        (Lang.SK, ANALYST),
        (Lang.SK, "fan"),
    ]
    assert [
        t.persona for t in narrative(fan="fallback").with_translations(["sk"]).translations
    ] == [ANALYST]
    assert [t.persona for t in narrative(fan=None).with_translations(["sk"]).translations] == [
        ANALYST
    ]
    with pytest.raises(ValueError, match="only once"):
        case.with_translations(["sk"]).with_translations(["sk"])
    open_ = narrative(fan=None).with_personas([Persona.FAN])
    with pytest.raises(ValueError, match="closed narrative"):
        open_.with_translations(["sk"])
    with pytest.raises(ValueError, match="closed narrative"):
        moment(7).with_translations(["sk"])
    with pytest.raises(ValueError, match="'en' is not a valid Lang"):
        case.with_translations(["en"])
    with pytest.raises(ValueError, match="whose own text did not pass"):
        dataclasses.replace(narrative(fan="fallback"), translations=(Translation("sk", "fan"),))
    with pytest.raises(ValueError, match="before its narrative"):
        dataclasses.replace(moment(7), translations=(Translation("sk", ANALYST),))
    with pytest.raises(ValueError, match="two translations"):
        dataclasses.replace(case, translations=(Translation("sk", ANALYST),) * 2)


def test_a_translation_takes_at_most_its_attempts_and_passes_only_on_a_pass():
    draft = narrative().narrative
    reject = REJECT
    t = Translation("sk", ANALYST)
    for n in range(1, TRANSLATION_ATTEMPTS + 1):
        t = t.with_attempt(Attempt(n, "fake", draft)).with_verdict(REJECT)
    assert t.is_open and not t.can_retry and t.fallback().outcome is RenditionOutcome.FALLBACK
    with pytest.raises(ValueError, match="at most 2"):
        Translation("sk", ANALYST, (*t.attempts, Attempt(3, "fake", draft, verdict=reject)))
    with pytest.raises(ValueError, match="but the last attempt passed"):
        Translation("sk", ANALYST, (), RenditionOutcome.PASSED)
    with pytest.raises(ValueError, match="'boss' is not a valid Persona"):
        Translation("sk", "boss")
    with pytest.raises(ValueError, match="is closed"):
        t.fallback().with_attempt(Attempt(3, "fake", draft))
    assert Translation.from_dict(t.to_dict()) == t


def test_what_a_persona_reads_in_slovak_is_the_translation_of_what_it_reads_in_english():
    case = narrative().with_translations(["sk"])
    analyst_sk = Draft(
        "Skóre je 0–1.", (dataclasses.replace(case.narrative.claims[0], text="Skóre je 0–1"),)
    )
    fan_sk = Draft(
        "Teraz je skóre 0–1.",
        (dataclasses.replace(case.narrative.claims[0], text="Teraz je skóre 0–1"),),
    )
    passed = Verdict(True, ())
    for persona, draft in ((ANALYST, analyst_sk), ("fan", fan_sk)):
        t = next(t for t in case.translations if t.persona == persona)
        case = case.with_translation(t.with_attempt(Attempt(1, "fake", draft)).with_verdict(passed))
    assert (
        case.translated_as_logged(ANALYST, "sk") == analyst_sk
        and case.translated_as_logged("fan", "sk") == fan_sk
    )
    assert case.source(case.translations[1]) == case.rendition("fan") != case.narrative
    fallen = narrative(fan="fallback").with_translations(["sk"])
    t = fallen.translations[0]
    fallen = fallen.with_translation(
        t.with_attempt(Attempt(1, "fake", analyst_sk)).with_verdict(passed)
    )
    assert fallen.translated_as_logged("fan", "sk") == analyst_sk  # the fan reads the narrative
    assert narrative().with_translations(["sk"]).translated_as_logged("fan", "sk") is None


# --- the log and the summary ------------------------------------------------------------------


def test_a_translation_travels_guard_translator_guard_and_out_only_when_closed(tmp_path):
    case = narrative().with_translations(["sk"])
    log = HandoffLog(tmp_path / "t.jsonl")
    log.record(Role.GUARD, Role.TRANSLATOR, case)
    with pytest.raises(ValueError, match="cannot go from guard to render"):
        Handoff("2026-10-25T10:00:00.000+00:00", Role.GUARD, Role.RENDER, case)
    with pytest.raises(ValueError, match="cannot go from translator to guard"):
        Handoff("2026-10-25T10:00:00.000+00:00", Role.TRANSLATOR, Role.GUARD, case)
    t = case.pending_translation.with_attempt(Attempt(1, "fake", case.narrative, requests=1))
    case = case.with_translation(t)
    log.record(Role.TRANSLATOR, Role.GUARD, case)
    lines = read_handoffs(log.path)
    assert [(h.sender, h.receiver) for h in lines] == [
        (Role.GUARD, Role.TRANSLATOR),
        (Role.TRANSLATOR, Role.GUARD),
    ]
    check_chain(lines)
    # a translator line that writes both translations at once is no single step
    other = case.translations[1].with_attempt(Attempt(1, "fake", case.narrative, requests=1))
    both = Handoff(lines[1].ts, Role.TRANSLATOR, Role.GUARD, case.with_translation(other))
    with pytest.raises(ValueError, match="no single step"):
        check_chain([lines[0], both])
    # a translation run's first line has no translation written yet
    started = Handoff(
        lines[0].ts,
        Role.GUARD,
        Role.TRANSLATOR,
        lines[1].case.with_translation(lines[1].case.translations[0].with_verdict(REJECT)),
    )
    with pytest.raises(ValueError, match="starts with a translation written"):
        check_chain([started])


def test_a_translation_run_s_summary_counts_its_attempts_and_not_the_run_s(tmp_path):
    cases = [narrative()]
    log = HandoffLog(tmp_path / "translate.sk.jsonl")
    script = by_moment({"m7-k0/analyst/sk": ["not json", echo], "m7-k0/fan/sk": [echo]})
    out = asyncio.run(translate(match(7), FakeChatClient(script), log, cases, langs=["sk"]))
    summary = summarize(read_handoffs(log.path))
    assert (summary.moments, summary.attempts, summary.model_requests) == (0, 0, 0)
    assert summary.personas == {} and summary.crashed == ()
    assert summary.translations.keys() == {"sk/analyst", "sk/fan"}
    analyst = summary.translations["sk/analyst"]
    assert (analyst["translations"], analyst["passed"], analyst["attempts"]) == (1, 1, 2)
    assert analyst["first_attempt_passed"] == 0 and analyst["errors"] == {"invalid_reply": 1}
    assert summary.total_requests == 3 and summary.models == ("fake",)
    (e,) = out
    assert [t.outcome for t in e.case.translations] == [RenditionOutcome.PASSED] * 2


# --- the Translator and its workflow ----------------------------------------------------------


def test_the_prompt_gives_the_source_its_claims_and_how_to_write_each_cited_fact():
    case = narrative().with_translations(["sk"])
    reading = next(f for f in case.facts if f["name"] == "goal_reading")
    claim = dataclasses.replace(
        case.narrative.claims[0], fact_ids=(*case.narrative.claims[0].fact_ids, reading["fact_id"])
    )
    case = dataclasses.replace(
        case,
        attempts=(
            dataclasses.replace(case.attempts[0], draft=Draft(case.narrative.text, (claim,))),
        ),
        translations=(),
    )
    case = case.with_translations(["sk"])
    prompt = translation_prompt(case, case.translations[0], match(7))
    lines = prompt.splitlines()
    assert (
        lines[0]
        == f"Translation into sk of analyst for moment m7-k0 at clock {case.display_clock}."
    )
    text = json.dumps(case.narrative.text, ensure_ascii=False)
    assert f"The English text that passed the Guard, the analyst's caption: {text}" in lines
    listed = {
        line.split(" | ")[0][2:]: line.split(" | ")[1] for line in lines if line.startswith("- m7/")
    }
    assert listed.keys() == set(claim.fact_ids)
    assert listed[reading["fact_id"]] == VOCABULARY_SK[reading["value"]]
    assert f"Source JSON: {json.dumps(case.narrative.to_dict(), ensure_ascii=False)}" in lines
    fan_case = narrative().with_translations(["sk"])
    fan = translation_prompt(fan_case, fan_case.translations[1], match(7))
    assert "the fan's rendition: " in fan and "Earlier attempts" not in fan


def test_the_request_carries_the_slovak_rules_and_a_retry_reads_its_reasons():
    case = narrative(fan=None).with_translations(["sk"])
    client = FakeChatClient(echo)
    t = case.translations[0]
    attempt = asyncio.run(Translator(client, match(7)).attempt(case, t))
    [(messages, options)] = client.requests
    assert [m.text for m in messages] == [translation_prompt(case, t, match(7))]
    assert options["instructions"] == translator.INSTRUCTIONS[Lang.SK]
    assert "Slovak" in options["instructions"] and options["instructions"].endswith(
        translator.RULES_SK
    )
    assert options["response_format"] == DRAFT_SCHEMA
    assert attempt.draft.text == case.narrative.text.replace(*SCORE_SK)
    rejected = t.with_attempt(Attempt(1, "fake", Draft("Nič.", ()))).with_verdict(
        check(Draft("Nič.", ()), case, moment_evidence(match(7), case), SK)
    )
    prompt = translation_prompt(case.with_translation(rejected), rejected, match(7))
    assert (
        'Earlier attempts, all rejected:\n- Attempt 1: "Nič."' in prompt
        and "  - no_claims: " in prompt
    )
    with pytest.raises(ValueError, match="no further attempt"):
        asyncio.run(Translator(client, match(7)).attempt(case, rejected.fallback()))
    waiting = t.with_attempt(Attempt(1, "fake", case.narrative))
    with pytest.raises(ValueError, match="not judged"):
        asyncio.run(Translator(client, match(7)).attempt(case.with_translation(waiting), waiting))


def test_the_workflow_retries_once_then_falls_back_and_keeps_to_the_budget(tmp_path):
    english = {"m7-k0/analyst/sk": [echo]}  # passes
    bad = lambda prompt: json.dumps({"text": "Skóre je dva.", "claims": []})  # noqa: E731
    script = by_moment(english | {"m7-k0/fan/sk": [bad, bad]})
    log = HandoffLog(tmp_path / "a.jsonl")
    (e,) = asyncio.run(
        translate(match(7), FakeChatClient(script), log, [narrative()], langs=["sk"])
    )
    analyst, fan = e.case.translations
    assert analyst.outcome is RenditionOutcome.PASSED and len(analyst.attempts) == 1
    assert fan.outcome is RenditionOutcome.FALLBACK and len(fan.attempts) == 2
    assert e.case.translated_as_logged("fan", "sk") is None
    routes = [(h.sender, h.receiver) for h in read_handoffs(log.path)]
    assert routes[0] == (Role.GUARD, Role.TRANSLATOR) and routes[-1] == (Role.GUARD, Role.RENDER)
    summarize(read_handoffs(log.path))  # one unbroken chain
    capped = HandoffLog(tmp_path / "b.jsonl")
    client = FakeChatClient(echo)
    (e,) = asyncio.run(
        translate(match(7), client, capped, [narrative()], langs=["sk"], max_calls=1)
    )
    assert len(client.requests) == 1
    analyst, fan = e.case.translations
    assert (
        fan.outcome is RenditionOutcome.FALLBACK and fan.attempts[0].error.code is CallError.SKIPPED
    )
    stats_only = moment(7).with_attempt(
        Attempt(1, "fake", None, error=CallFailure(CallError.TIMEOUT, "x"))
    )
    stats_only = stats_only.with_verdict(judge(stats_only, moment_evidence(match(7), stats_only)))
    stats_only = stats_only.stats_only()
    assert (
        asyncio.run(
            translate(
                match(7),
                FakeChatClient([]),
                HandoffLog(tmp_path / "c.jsonl"),
                [stats_only],
                langs=["sk"],
            )
        )
        == []
    )


# --- the command and the replay -------------------------------------------------------------


@pytest.fixture
def a_run(tmp_path):
    """A `--fake` explain run of m7 up to 28:20 with fan renditions, and its recap."""
    argv = [
        "explain",
        "m7",
        "--fake",
        "--until",
        "28:20",
        "--runs",
        str(tmp_path),
        "--persona",
        "fan",
    ]
    assert cli.main(argv) == 0
    (run,) = (tmp_path / "m7").iterdir()
    assert cli.main(["recap", "m7", "--run", str(run), "--fake", "--persona", "fan"]) == 0
    return run


def test_translate_command_writes_its_log_and_summary_and_the_page_shows_slovak(a_run, capsys):
    capsys.readouterr()
    assert cli.main(["translate", "m7", "--run", str(a_run), "--lang", "sk", "--fake"]) == 0
    out, err = capsys.readouterr()
    assert "  sk/analyst passed (1): Skóre je " in out and "translate.sk.jsonl" in err
    assert "sk/analyst: 4 translations: 4 passed, 0 fallback to the English text" in out
    summary = json.loads((a_run / "translate.sk.json").read_text())
    assert summary["settings"] == {"max_calls": 40, "pace_s": 0, "lang": "sk"}
    assert summary["translations"]["sk/fan"]["passed"] == 4 and summary["total_requests"] == 8
    assert cli.main(["cues", "--seed", "7", "--run", str(a_run)]) == 0
    out, err = capsys.readouterr()
    assert "m7: 6 sk translations from the run, 0 refused at replay; 2 on the recap\n" in err
    cues = json.loads(out)["cues"]
    moments = [c for c in cues if c["kind"] == "moment"]
    heads = [c["translations"]["sk"]["analyst"]["lines"][0].split(" · ")[0] for c in moments]
    assert heads == ["Analytik"] * 3 + ["Kľúčový moment"] * (len(moments) - 3)  # run to 28:20
    sk = [c["translations"]["sk"] for c in moments[:3]]
    assert all(t["analyst"]["lines"][1].startswith("Skóre je ") for t in sk)
    assert [t["fan"]["lines"][0].split(" · ")[0] for t in sk] == ["Pre fanúšika"] * 3
    (recap,) = [c for c in cues if c["kind"] == "recap"]
    assert recap["translations"]["sk"]["analyst"]["lines"] == ["Zhrnutie", "Skóre je 3–2."]
    assert recap["translations"]["sk"]["fan"]["lines"][0] == "Zhrnutie pre fanúšika"


def test_translate_command_refuses_a_second_run_another_match_and_a_model_without_a_cap(
    a_run, capsys
):
    assert cli.main(["translate", "m7", "--run", str(a_run), "--lang", "sk", "--fake"]) == 0
    capsys.readouterr()
    run, none = str(a_run), str(a_run / "none")
    for argv, message in (
        (["translate", "m7", "--run", run, "--lang", "sk", "--fake"], "translations already"),
        (["translate", "m8", "--run", run, "--lang", "sk", "--fake"], "is no run of m8"),
        (["translate", "m7", "--run", run, "--lang", "sk"], "needs --max-calls"),
        (["translate", "m7", "--run", run, "--lang", "de", "--fake"], "invalid choice"),
        (["translate", "m7", "--run", none, "--lang", "sk", "--fake"], "cannot read the run"),
    ):
        with pytest.raises(SystemExit) as exit_:
            cli.main(argv)
        assert exit_.value.code == 2
        assert message in capsys.readouterr().err


def run_handoffs(run) -> list:
    """The run's moments' lines (`moment_cues` takes no recap)."""
    return read_handoffs(run / "handoffs.jsonl")


def test_the_replay_judges_each_translation_again_and_shows_english_for_a_refused_one(
    a_run, capsys
):
    assert cli.main(["translate", "m7", "--run", str(a_run), "--lang", "sk", "--fake"]) == 0
    translated = read_handoffs(a_run / "translate.sk.jsonl")
    out = [h for h in translated if h.receiver is Role.RENDER and not h.case.is_recap]
    first = out[0].case
    t = first.translations[0]
    broken = Draft(
        t.draft.text.replace("–", "-"), t.draft.claims
    )  # a numeral no longer the source's
    claims = tuple(dataclasses.replace(c, text=c.text.replace("–", "-")) for c in broken.claims)
    tampered = dataclasses.replace(
        t, attempts=(dataclasses.replace(t.attempts[0], draft=Draft(broken.text, claims)),)
    )
    out[0] = dataclasses.replace(out[0], case=first.with_translation(tampered))
    cues = moment_cues(match(7), [*run_handoffs(a_run), *out])
    cue = next(c for c in cues if c.cue_id.endswith(first.moment_id))
    assert cue.translated(ANALYST, "sk").lines == cue.lines  # English, as the run's narrative
    assert cue.translated("fan", "sk").lines[0].startswith("Pre fanúšika · ")
    with pytest.raises(ValueError, match="closed twice"):
        moment_cues(match(7), [*run_handoffs(a_run), *out, *out])
    with pytest.raises(ValueError, match="closed twice"):
        closing(first, dataclasses.replace(first, run_id="r2"))
    assert closing(None, first) == first
    assert not any(t.persona == ANALYST for t in cue.translations)  # no English one in its place
    original = next(
        h.case
        for h in run_handoffs(a_run)
        if h.case.moment_id == first.moment_id and h.receiver is Role.RENDER
    )
    other = dataclasses.replace(first, run_id="r2")  # the same moment from another run
    with pytest.raises(ValueError, match="closed twice"):
        closing(original, other)
    assert closing(original, first) == first


def test_a_translation_shows_only_while_its_english_source_passes_again(a_run):
    """A translation the Slovak Guard passes is not shown for a source the English Guard now
    refuses: the cue falls back to the facts, in Slovak words."""
    assert cli.main(["translate", "m7", "--run", str(a_run), "--lang", "sk", "--fake"]) == 0
    closed = [
        h
        for h in read_handoffs(a_run / "translate.sk.jsonl")
        if h.receiver is Role.RENDER and not h.case.is_recap
    ]
    case = closed[0].case
    assert case.translated_as_logged(ANALYST, "sk") is not None
    narrative = case.narrative
    judged = Draft(narrative.text + " They lead.", narrative.claims)  # refused in English now
    attempt = dataclasses.replace(case.attempts[-1], draft=judged)
    tampered = dataclasses.replace(case, attempts=(*case.attempts[:-1], attempt))
    cues = moment_cues(match(7), [dataclasses.replace(closed[0], case=tampered)])
    cue = next(c for c in cues if c.cue_id.endswith(case.moment_id))
    assert cue.lines[0].startswith("Key moment · ")
    sk = cue.translated(ANALYST, "sk").lines
    assert sk[0].startswith("Kľúčový moment · ") and sk[1].startswith("minúta ")
    assert cue.translated("fan", "sk").lines == sk  # the fan reads the facts too


def test_a_retry_s_hint_names_the_shirt_number_s_context_in_the_draft_s_language():
    case, evidence = goal()
    m = match(7)
    scorer = next(e for e in m.events if e.event_id == case.trigger_ids[-1]).player
    shirt = next(
        f for f in evidence.facts.values() if f.name == "shirt_number" and f.player == scorer
    )
    claim = Claim(f"hráč {shirt.display}", (shirt.fact_id,), case.trigger_ids[-1:])
    for lang, needs in (("en", "'No.'"), (SK, "'č.'")):
        (reason,) = check(Draft(claim.text + ".", (claim,)), case, evidence, lang).reasons
        assert reason.code is ReasonCode.NUMBER_NOT_CITED and needs in reason.detail


def test_translate_command_says_when_there_is_nothing_to_translate(tmp_path, capsys):
    stats_only = moment(7).with_attempt(
        Attempt(1, "fake", None, error=CallFailure(CallError.TIMEOUT, "x"))
    )
    stats_only = stats_only.with_verdict(judge(stats_only, moment_evidence(match(7), stats_only)))
    HandoffLog(tmp_path / "handoffs.jsonl").record(Role.GUARD, Role.RENDER, stats_only.stats_only())
    assert cli.main(["translate", "m7", "--run", str(tmp_path), "--lang", "sk", "--fake"]) == 0
    err = capsys.readouterr().err
    assert (
        "no log (no narrative to translate)" in err
        and not (tmp_path / "translate.sk.jsonl").exists()
    )
    assert json.loads((tmp_path / "translate.sk.json").read_text())["translations"] == {}


def test_without_a_run_every_cue_and_the_recap_have_their_slovak_lines():
    overlay = match_overlay(match(7))
    for cue in overlay.cues:
        for persona in ("analyst", "fan"):
            mine = cue.translated(persona, "sk")
            assert mine.lang == "sk" and mine.fact_ids, (cue.cue_id, persona)
    recap = match_recap(match(7))
    assert recap.translations["sk"]["analyst"][0] == "Koniec zápasu vo faktoch"
    assert recap.to_dict()["translations"]["sk"]["analyst"]["source"] == "engine"
    assert recap.translations["sk"]["fan"] == recap.translations["sk"]["analyst"]


def test_druhy_counting_a_goal_stays_a_number_beside_the_places_that_are_none():
    case, evidence = goal()
    good = caption(case, evidence, [], SK)
    for words, passes in (("druhý gól", False), ("druhú strelu", False), ("druhú žrď", False),
                          ("na druhú žrď", True), ("druhá polovica", False)):  # fmt: skip
        verdict = check(Draft(f"{good.text} Teraz {words}.", good.claims), case, evidence, SK)
        assert verdict.passed == passes, (words, verdict.reasons)


def _recap_run(a_run, persona: str):
    """The run's recap closed again by its translation run, the translation of `persona` made
    to change a numeral of its source."""
    assert cli.main(["translate", "m7", "--run", str(a_run), "--lang", "sk", "--fake"]) == 0
    closed = read_handoffs(a_run / "translate.sk.jsonl")
    (out,) = [h for h in closed if h.receiver is Role.RENDER and h.case.is_recap]
    case = out.case
    t = next(t for t in case.translations if t.persona == persona)
    broken = Draft(t.draft.text.replace("–", "-"), t.draft.claims)
    claims = tuple(dataclasses.replace(c, text=c.text.replace("–", "-")) for c in broken.claims)
    tampered = dataclasses.replace(
        t, attempts=(dataclasses.replace(t.attempts[0], draft=Draft(broken.text, claims)),)
    )
    return [
        *read_handoffs(a_run / "recap.jsonl"),
        dataclasses.replace(out, case=case.with_translation(tampered)),
    ]


@pytest.mark.parametrize("persona", [ANALYST, "fan"])
def test_a_recap_s_refused_translation_leaves_its_english_text_and_no_slovak_entry(a_run, persona):
    recap = match_recap(match(7), _recap_run(a_run, persona))
    other = "fan" if persona == ANALYST else ANALYST
    assert persona not in recap.translations["sk"]  # the English text stands in, not as Slovak
    assert recap.translations["sk"][other][0] in ("Zhrnutie", "Zhrnutie pre fanúšika")
    cue = recap.cue()
    assert cue.translated(persona, "sk").lines == cue.rendition(persona).lines
    assert recap.to_dict()["translations"]["sk"].keys() == {other}


def test_the_fan_reads_its_english_rendition_when_only_its_own_translation_is_refused(a_run):
    assert cli.main(["translate", "m7", "--run", str(a_run), "--lang", "sk", "--fake"]) == 0
    out = [
        h
        for h in read_handoffs(a_run / "translate.sk.jsonl")
        if h.receiver is Role.RENDER and not h.case.is_recap
    ]
    case = out[0].case
    t = next(t for t in case.translations if t.persona == "fan")
    claims = tuple(dataclasses.replace(c, text=c.text.replace("–", "-")) for c in t.draft.claims)
    broken = Draft(t.draft.text.replace("–", "-"), claims)
    tampered = dataclasses.replace(t, attempts=(dataclasses.replace(t.attempts[0], draft=broken),))
    out[0] = dataclasses.replace(out[0], case=case.with_translation(tampered))
    cues = moment_cues(match(7), [*run_handoffs(a_run), *out])
    cue = next(c for c in cues if c.cue_id.endswith(case.moment_id))
    assert cue.translated(ANALYST, "sk").lines[0].startswith("Analytik · ")
    assert cue.translated("fan", "sk").lines == cue.rendition("fan").lines  # its English
    assert cue.rendition("fan").lines[0].startswith("Fan view · ")


def test_a_slovak_deterministic_recap_the_guard_refuses_is_a_bug(monkeypatch):
    import matchlens.render.recap as render_recap

    real_fallback = render_recap.fallback_recap

    def broken(match_, case, evidence, lang="en"):
        draft = real_fallback(match_, case, evidence, lang)
        return draft if lang == "en" else Draft(draft.text + " Dve strely.", draft.claims)

    monkeypatch.setattr(render_recap, "fallback_recap", broken)
    with pytest.raises(RuntimeError, match="the sk recap of m7 fails the Guard: number_word"):
        match_recap(match(7))

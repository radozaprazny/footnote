"""Overlay cues: the cards the page shows over the replayed match, built from facts only.

A cue is due at a moment of the match, (period, clock_ms), and says only what is known then:
its facts come from `facts_at(due)`, or are whole-match facts (`match_facts`) whose evidence ends
at or before `due` (shot speed at a shot). Its text is fixed wording, club
and player names from the league, and the `display` of the facts it cites; it never carries a
numeral of its own. A key moment's narrative (`render.moments`) is the exception: the Analyst
wrote it and the Guard passed it, so its numbers are cited facts in the forms the Guard accepts
(`68th`, `3-2`), not always their literal displays. `event_ids` and `frame_ids` are the cue's
trigger, the evidence of each fact stays with the fact (looked up by `fact_ids`); no cue sets
`frame_ids` since the full-time card lost its top speed, the field stays for the JSON contract. A
stream schedules a cue by `due`, never by its events: a chance is due when the ball arrives, after
the shot it names.

Kinds, in the order the page shows cues due at the same moment: the end of a period (score,
possession, pass completion), a goal (scorer, minute, score, shot
speed of a hard shot), a chance (a saved shot or one off the woodwork, when the ball arrives), a
key moment (the Explain stage's text, `render.moments`; after the goal or chance it explains),
every fifth minute of a period (momentum, pressing and chaos over the last five minutes) and the
recap at full time (`render.recap`, after the full-time cue; its facts are the whole match's
and those of each goal's instant).

Personas: `lines` and `fact_ids` are what the analyst reads, every number the engine has. Each cue
also carries a rendition per persona (`renditions`; M5: the fan) with its own lines and the facts
they cite, under the same rules. The fan's lines judge with the engine's readings instead of
percentages ("COR on top · a steady tempo", "VEL take the lead"): a reading's phrase is its
`display`, and a reading of a club follows that club's short name, last before the phrase in the
line. Without a reading to say it, the fan reads a window as the analyst does, a period end as its
score and a goal as its scorer and the score.

Languages: a cue also carries its lines in each language a page may show (`translations`; M5:
Slovak), for the analyst and for each persona, built by the same templates in that language's
words (`WORDS`, `VERBS`) with the same facts; a reading's phrase is its phrase in that language
(`stats.readings.PHRASES`). Numbers, names and fact ids stay as they are.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from matchlens.events import Event, EventType, Outcome
from matchlens.explain.state import ANALYST, Lang, Persona
from matchlens.facts import WINDOW_MS, Fact, Time, facts_at, match_facts
from matchlens.league import load_league
from matchlens.match import Match
from matchlens.stats.readings import PHRASES


class CueKind(StrEnum):
    PERIOD_END = "period_end"
    GOAL = "goal"
    CHANCE = "chance"
    MOMENT = "moment"
    WINDOW = "window"
    RECAP = "recap"


ORDER = tuple(CueKind)  # the page's order for cues due at the same moment
TTL_MS = {  # how long the page shows a cue, in wall-clock time whatever the replay speed
    CueKind.PERIOD_END: 10_000,
    CueKind.GOAL: 8_000,
    CueKind.CHANCE: 5_000,
    CueKind.MOMENT: 8_000,
    CueKind.WINDOW: 6_000,
    CueKind.RECAP: 20_000,  # 3 to 5 sentences
}
CHANCES = (Outcome.SAVED, Outcome.WOODWORK)
PERSONAS = (ANALYST, *(p.value for p in Persona))
FAVOURED = ("on_top", "more_of_the_ball")  # of two readings that differ, the one a fan line names
EN = "en"  # the language of a cue's own lines
# a cue's fixed words in each language
WORDS = {
    EN: {
        Outcome.SAVED: "Saved",
        Outcome.WOODWORK: "Off the woodwork",
        "goal": "GOAL",
        "shot_speed": "Shot speed",
        "recent": "Recent play to {}",
        "momentum": "Momentum",
        "pressing_per_minute": "Pressing / min",
        "chaos": "Chaos index",
        "half_time": "Half time",
        "full_time": "Full time",
        "possession": "Possession",
        "pass_completion": "Pass completion",
        "and": "and",
    },
    Lang.SK: {
        Outcome.SAVED: "Chytená strela",
        Outcome.WOODWORK: "Strela do konštrukcie",
        "goal": "GÓL",
        "shot_speed": "Rýchlosť strely",
        "recent": "Posledné minúty do {}",
        "momentum": "Momentum",
        "pressing_per_minute": "Presing / min",
        "chaos": "Index chaosu",
        "half_time": "Polčas",
        "full_time": "Koniec zápasu",
        "possession": "Držanie lopty",
        "pass_completion": "Úspešnosť prihrávok",
        "and": "a",
    },
}
# the verb before a team reading's phrase in a fan line, for one club and for two: English says
# "COR on top" and "COR have more of the ball", a Slovak phrase of momentum or possession needs one
VERBS = {
    EN: {"more_of_the_ball": " have", "less_of_the_ball": " have", "even_share": " have"},
    Lang.SK: {
        "on_top": (" má", " majú"),
        "pinned_back": (" je", " sú"),
        "evenly_matched": (" hrá", " hrajú"),
        "more_of_the_ball": (" má", " majú"),
        "less_of_the_ball": (" má", " majú"),
        "even_share": (" má", " majú"),
    },
}


@dataclass(frozen=True)
class CueRendition:
    """A cue's text for one persona in one language: its lines, the facts they cite, the cue's
    trigger events."""

    persona: str
    lines: tuple[str, ...]
    fact_ids: tuple[str, ...]
    event_ids: tuple[str, ...] = ()
    lang: str = EN

    def to_dict(self) -> dict:
        return {
            "lines": list(self.lines),
            "fact_ids": list(self.fact_ids),
            "event_ids": list(self.event_ids),
        }


@dataclass(frozen=True)
class Cue:
    cue_id: str
    match_id: str
    due: Time
    kind: CueKind
    lines: tuple[str, ...]
    fact_ids: tuple[str, ...]
    team: str | None = None
    event_ids: tuple[str, ...] = ()
    frame_ids: tuple[str, ...] = ()
    ttl_ms: int = 0
    anchor: tuple[float, float] | None = None  # where on the pitch, metres
    renditions: tuple[CueRendition, ...] = ()  # one per persona other than the analyst
    translations: tuple[CueRendition, ...] = ()  # per language, one per persona and the analyst

    def with_translation(self, there: "Cue", lang: str) -> "Cue":
        """This cue with the analyst's and each persona's lines of `there`, the same cue built in
        the words of `lang`."""
        added = [CueRendition(ANALYST, there.lines, there.fact_ids, there.event_ids, lang)]
        added += [replace(r, lang=lang) for r in there.renditions]
        return replace(self, translations=(*self.translations, *added))

    def rendition(self, persona: str) -> CueRendition:
        """What `persona` reads: its own rendition, else the analyst's lines."""
        mine = next((r for r in self.renditions if r.persona == persona), None)
        return mine or CueRendition(ANALYST, self.lines, self.fact_ids, self.event_ids)

    def translated(self, persona: str, lang: str) -> CueRendition:
        """What `persona` reads in `lang`: its lines there, else what it reads in English."""
        mine = (t for t in self.translations if (t.persona, t.lang) == (persona, lang))
        return next(mine, None) or self.rendition(persona)

    def to_dict(self) -> dict:
        """Plain JSON types: tuples become lists, renditions an object by persona."""
        return {
            "cue_id": self.cue_id,
            "match_id": self.match_id,
            "due": list(self.due),
            "kind": self.kind.value,
            "lines": list(self.lines),
            "fact_ids": list(self.fact_ids),
            "team": self.team,
            "event_ids": list(self.event_ids),
            "frame_ids": list(self.frame_ids),
            "ttl_ms": self.ttl_ms,
            "anchor": None if self.anchor is None else list(self.anchor),
            "renditions": {r.persona: r.to_dict() for r in self.renditions},
            "translations": {
                lang: {t.persona: t.to_dict() for t in self.translations if t.lang == lang}
                for lang in dict.fromkeys(t.lang for t in self.translations)
            },
        }


def cue_timeline(match: Match, whole: Sequence[Fact] | None = None) -> list[Cue]:
    """Every cue of `match`, in the order the page shows them. `whole`: the match's
    `match_facts`, if already computed (they take about 4 s)."""
    whole = match_facts(match) if whole is None else whole
    if any(f.match_id != match.meta.match_id for f in whole):
        raise ValueError(f"facts of another match than {match.meta.match_id}")
    cues = _timeline(_Builder(match, whole))
    for lang in Lang:  # the same cues, in each language's words
        there = {c.cue_id: c for c in _timeline(_Builder(match, whole, lang))}
        cues = [c.with_translation(there[c.cue_id], lang) for c in cues]
    return cues


def _timeline(builder: "_Builder") -> list[Cue]:
    match = builder.match
    events = match.events
    by_id = {e.event_id: e for e in events}
    ends = {e.period: e.clock_ms for e in events if e.type is EventType.PERIOD_END}
    cues = []
    for e in events:
        if e.type is EventType.PERIOD_END:
            cues.append(builder.period_end(e))
            cues += [builder.window(e.period, t) for t in window_times(e.clock_ms)]
        elif e.type is EventType.GOAL:
            cues.append(builder.shot(by_id[e.related], (e.period, e.clock_ms), goal=e))
        elif e.type is EventType.SHOT and e.outcome in CHANCES:
            if (due := chance_due(e, ends[e.period])) is not None:
                cues.append(builder.shot(e, due))
    return ordered(c for c in cues if c is not None)


def ordered(cues: Iterable[Cue]) -> list[Cue]:
    """By due moment, then kind (`ORDER`), then id."""
    return sorted(cues, key=lambda c: (c.due, ORDER.index(c.kind), c.cue_id))


def chance_due(shot: Event, period_end_ms: int) -> Time | None:
    """When the ball of a saved shot or one off the woodwork arrives; None if after the period's
    end (no fact speaks of that moment)."""
    arrives = shot.clock_ms + shot.duration_ms
    return (shot.period, arrives) if arrives <= period_end_ms else None


def window_times(period_end_ms: int) -> list[int]:
    """The clocks of a period's window cues: every fifth minute before the period ends (at its
    end the period cue speaks)."""
    return list(range(WINDOW_MS, period_end_ms, WINDOW_MS))


class _Builder:
    def __init__(self, match: Match, whole: Sequence[Fact], lang: str = EN) -> None:
        self.match = match
        self.meta = match.meta
        self.whole = whole
        self.words, self.verbs = WORDS[lang], VERBS[lang]
        self.phrases = PHRASES[lang]
        league = load_league()
        self.clubs = {c.id: c for c in league.clubs}
        self.players = {p.id: p for c in league.clubs for p in c.players}

    def cue(self, kind: CueKind, trigger: str, due: Time, lines, facts, fan=None, **kw) -> Cue:
        """`fan`: the fan's lines and facts; None: the fan reads the analyst's."""
        match_id = self.meta.match_id
        fan_lines, fan_facts = fan or (lines, facts)
        event_ids = kw.get("event_ids", ())
        return Cue(
            f"{match_id}/cue/{kind.value}/{trigger}",
            match_id,
            due,
            kind,
            tuple(lines),
            _ids(facts),
            ttl_ms=TTL_MS[kind],
            renditions=(
                CueRendition(Persona.FAN.value, tuple(fan_lines), _ids(fan_facts), event_ids),
            ),
            **kw,
        )

    def club(self, team: str) -> str:
        return self.clubs[team].short_name

    def player(self, player: str, at: dict[tuple, Fact]) -> tuple[str, Fact]:
        """`Name #7`, and the shirt number fact behind it."""
        number = at["shirt_number", player]
        return f"{self.players[player].name} #{number.display}", number

    def score_line(self, at: dict[tuple, Fact]) -> tuple[str, Fact]:
        score = _one(at, "score")
        return f"{self.club(self.meta.home)} {score.display} {self.club(self.meta.away)}", score

    def pairs(
        self, at: dict[tuple, Fact], stamp: str, names: tuple[str, ...]
    ) -> tuple[list[str], list[Fact]]:
        """`Momentum COR 52% – 48% SLT` for each fact of `names` known for both clubs."""
        home, away = self.meta.home, self.meta.away
        lines, facts = [], []
        for name in names:
            label = self.words[name]
            pair = at.get((name, stamp, home)), at.get((name, stamp, away))
            if None not in pair:
                lines.append(
                    f"{label} {self.club(home)} {pair[0].display} – {pair[1].display} "
                    f"{self.club(away)}"
                )
                facts += pair
        return lines, facts

    def phrase(self, reading: Fact, clubs: int = 1) -> str:
        """A reading's phrase in the builder's language, after the verb it needs there for one
        club or for two (`VERBS`)."""
        verb = self.verbs.get(reading.value, "")
        if isinstance(verb, tuple):
            verb = verb[clubs - 1]
        return f"{verb} {self.phrases[reading.value]}"

    def team_reading(
        self, at: dict[tuple, Fact], name: str, stamp: str
    ) -> tuple[str, list[Fact]] | None:
        """A fan's phrase for a pair of team readings: `COR on top` (the favoured one of two that
        differ), `SLT and COR evenly matched` (the same for both); None without the pair."""
        home, away = self.meta.home, self.meta.away
        h, a = at.get((name, stamp, home)), at.get((name, stamp, away))
        if h is None or a is None:
            return None
        if h.value == a.value:
            both = f"{self.club(home)} {self.words['and']} {self.club(away)}"
            return f"{both}{self.phrase(a, 2)}", [h, a]
        named = next((f for f in (h, a) if f.value in FAVOURED), h)
        return f"{self.club(named.team)}{self.phrase(named)}", [named]

    def judged(self, at: dict[tuple, Fact], stamp: str, team: tuple) -> tuple[str, list[Fact]]:
        """`COR on top · a steady tempo`: the first team reading of the names in `team` the
        engine has, then the chaos reading; empty if it has neither."""
        parts, facts = [], []
        for name in team:
            if (found := self.team_reading(at, name, stamp)) is not None:
                parts.append(found[0])
                facts += found[1]
                break
        if (chaos := at.get(("chaos_reading", stamp, "all"))) is not None:
            parts.append(self.phrases[chaos.value])
            facts.append(chaos)
        return " · ".join(parts), facts

    def shot(self, shot: Event, due: Time, goal: Event | None = None) -> Cue:
        """A goal cue (with the score) if `goal`, else a chance cue; either with the shot's speed
        if it is a hard shot (the engine has no speed for the others). The fan reads the player,
        and for a goal what it does for the club and the score; for a chance the club and the
        player without the minute, and the shot's speed."""
        at = _known(self.match, due)
        who, number = self.player(shot.player, at)
        minute = _one(at, "minute")
        header = self.words[shot.outcome if goal is None else "goal"]
        lines = [f"{header} · {self.club(shot.team)}", f"{who} · {minute.display}"]
        facts = [number, minute]
        fan_lines = (
            [f"{header} · {who}"] if goal else [lines[0], who]
        )  # the club: who saved, who shot
        fan_facts = [number]
        triggers = [shot]
        if goal is not None:
            score_line, score = self.score_line(at)
            lines.append(score_line)
            facts.append(score)
            stamp = f"at-{goal.period}-{goal.clock_ms}"
            if (reading := at.get(("goal_reading", stamp, goal.team))) is not None:
                fan_lines.append(f"{self.club(goal.team)}{self.phrase(reading)}")
                fan_facts.append(reading)
            fan_lines.append(score_line)
            fan_facts.append(score)
            triggers.append(goal)
        speeds = (
            f for f in self.whole if f.name == "shot_speed" and f.event_ids[:1] == (shot.event_id,)
        )
        if (speed := next(speeds, None)) is not None:
            lines.append(f"{self.words['shot_speed']} {speed.display} {speed.unit}")
            facts.append(speed)
            if goal is None:
                fan_lines.append(lines[-1])
                fan_facts.append(speed)
        return self.cue(
            CueKind.CHANCE if goal is None else CueKind.GOAL,
            triggers[-1].event_id,
            due,
            lines,
            facts,
            (fan_lines, fan_facts),
            team=shot.team,
            event_ids=tuple(e.event_id for e in triggers),
            anchor=(shot.start.x, shot.start.y),
        )

    def window(self, period: int, clock_ms: int) -> Cue | None:
        """None if nothing happened in the window to speak of."""
        due = (period, clock_ms)
        at = _known(self.match, due)
        stamp = f"last5-{period}-{clock_ms}"
        clock = _one(at, "clock")
        pair_lines, pair_facts = self.pairs(at, stamp, ("momentum", "pressing_per_minute"))
        lines = [self.words["recent"].format(clock.display), *pair_lines]
        facts = [clock, *pair_facts]
        if (chaos := at.get(("chaos", stamp, "all"))) is not None:
            lines.append(f"{self.words['chaos']} {chaos.display}")
            facts.append(chaos)
        if len(facts) == 1:
            return None
        judged, judging = self.judged(at, stamp, ("momentum_reading", "possession_reading"))
        fan = ([lines[0], judged], [clock, *judging]) if judged else None
        return self.cue(CueKind.WINDOW, f"{period}-{clock_ms}", due, lines, facts, fan)

    def period_end(self, end: Event) -> Cue:
        due = (end.period, end.clock_ms)
        at = _known(self.match, due)
        stamp = f"to-{end.period}-{end.clock_ms}"
        score_line, score = self.score_line(at)
        pair_lines, pair_facts = self.pairs(at, stamp, ("possession", "pass_completion"))
        lines = [self.words["half_time" if end.period == 1 else "full_time"], score_line]
        lines += pair_lines
        facts = [score, *pair_facts]
        judged, judging = self.judged(at, stamp, ("possession_reading",))
        fan = (lines[:2], [score]) if not judged else (lines[:2] + [judged], [score, *judging])
        # no player's top speed (issue #7): outfield players close down at `APPROACH_SPEED`
        # (6.5 m/s; measured top speeds 6.10–6.63 m/s, seeds 0–49), far below a real 9–10 m/s,
        # so the number would look wrong on screen; the engine keeps the fact
        return self.cue(
            CueKind.PERIOD_END, end.event_id, due, lines, facts, fan, event_ids=(end.event_id,)
        )


def _known(match: Match, due: Time) -> dict[tuple, Fact]:
    """`facts_at(due)` by (name, scope, player or team or 'all'), and by (name, player) for
    the shirt numbers."""
    at: dict[tuple, Fact] = {}
    for f in facts_at(match, *due):
        name, scope, who = f.fact_id.split("/")[1:]
        at[name, scope, who] = f
        if name == "shirt_number":
            at[name, who] = f
        at.setdefault((name,), f)
    return at


def _ids(facts: Iterable[Fact]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(f.fact_id for f in facts))


def _one(at: dict[tuple, Fact], name: str) -> Fact:
    """The fact of `name` that `facts_at` gives once (clock, minute, score)."""
    return at[(name,)]

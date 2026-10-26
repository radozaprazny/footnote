"""The Guard: a deterministic check of an Analyst draft against the stats engine. Never an LLM.

A draft passes only when every number in it lies inside a claim and is the `display` of a fact
that claim cites, every cited fact exists in the engine at that moment, every claim names its
evidence (event or frame ids that exist and belong to a cited fact or to the moment's triggers),
and every capitalized name is a player of the two lineups or one of the two clubs. The Guard
reads its facts from the engine (`moment_evidence`), never from the case. A match's recap at full
time is judged by the same rules against the whole match's facts (`recap_evidence`), in at most
`RECAP_MAX_TEXT` characters, and must state the final score in a claim that cites it.

How numbers are read: digits only, in the forms the engine displays (`52%`, `12.7`, `67:23`,
`45+2:13`, `68'`, `45+3'`, `3–2`; a minute also as an ordinal, `68th`; a clock also without its
leading zero, `9:05`). Two numbers joined by a dash, a slash, a colon or "to" read as one score,
`2–1`. Coverage is by position: a numeral counts as inside a claim only when its whole span lies
within an occurrence of that claim's text. A fact with a unit word (`km`) needs the unit after
the number, a shirt number needs `No.`, `number`, `#` or `shirt` around it, and a fact of the
last five minutes needs "last 5 minutes" in its claim. Refused: numbers in words (`two`, `nil`,
`brace`, `only once`, `half of`, `a couple of`, `ninetieth`, `one-nil`, `first goal`), numeric
characters other than ASCII digits (`½`, `²`), any other numeral form (`52 per cent`, `68
minutes`, a score in reverse order), and drafts over `MAX_TEXT` characters or `MAX_CLAIMS`
claims. Fixed football phrases with a number (`six-yard box`, `one-two`, `final third`, `the
back four` but not "hit back five minutes later", `a third-man run`) are no claims.

How judgements are read: the engine's readings (`stats.readings.VOCABULARY`: "take the lead",
"on top", "more of the ball") are the only words that may judge the score or the play. A phrase
of the vocabulary (any case; a hyphen or a space between its words) must lie inside a claim that
cites a reading whose display is that phrase; a reading of a team also needs that team named
before the phrase in the claim: the last club or player name of the match there is of that team
("Vellbridge Town take the lead", and "Malik Sennabe scores and they take the lead" for his
club; "Vellbridge Town beat Quarrendale Rovers and take the lead" is refused).
Refused anywhere else: the words that judge without a reading (`lead`, `leading`, `ahead`,
`level`, `equaliser`, `opener`, `winner`, `comeback`, `goalless`, `dominate`, `in control`,
`chaotic`, `calm`, `outshoot`, `behind`, `trailing`, `superior`, `in command`, `took control`,
`a goal up`, `2–1 up`, `opens the scoring`, `deadlock`, `hit back`, `cancel out`, `more`,
`fewer`, `less` or `most` within three words of `ball`, `possession`, `shots`, `passes` or
`chances`, `behind`/`ahead of` anything but a place, `fightback`, `pegged back`, `back on
terms`, the result in words: `beat`, `unbeaten`, `win`, `won`, `lose`, `lost`, `loss`,
`defeat`, `undefeated`, `victory`, `stalemate`, `overcame`, `prevail`, `draw`, `redraw`, `tie`,
`winnable`, `see them off`, `edge` but the edge of a place, in any of their forms, and
`point` or `points` but exactly `at this point`, `at that point` and `point-blank`, which in a
caption can only be the league's)
and the vocabulary's words in another form (`led`, `levelled`, `equalises`, `claw one back`,
`pinning back`, `come from behind`). Ordinary football words near them pass: `in front of
goal`, `ahead of the runner`, `winning the ball`, `leads to a shot` (not "to 3–1"), `the
lead-up`, `level of`, `gets in behind`, `67:23 down the right`,
`on top of the ball`, `a tackle from behind`, `behind the defence`, `takes advantage of`,
`beats the keeper`, `beat the press`, `wins a corner`, `won back possession` (not `won the
possession battle`), `wins the loose ball`, `wins it back`, `lost the ball`, `loses his footing`,
`draws a fine save`, `draws the keeper`, `the edge of the box`, `point-blank` (an exception of
a result word names its object after an article, `possession` and `it back` without one, and no
number may follow it directly: `beats defenders`, `won possession 58% to 42%`, `beat the keeper
3–2` are refused). A
reading's window must be its claim's: a reading of the last 5 minutes only in a claim that
says "last 5 minutes", any other only in a claim that does not and that names no window in
other words either ("recently", "in this spell", "over the last few minutes", "in the second
half"); in a recap a reading's phrase stands in no claim that also cites a fact of the other
time: a whole-match reading beside a goal's minute or score, a goal's reading beside a fact of
the whole match or beside another goal's minute, score or reading.

Known limits (Follow-ups): the Guard checks that a number is a cited display, not what the
sentence says it counts (`Corrowmere have 1 shot` citing their 1 goal passes, as do two goal
counts written `2, 1`); words that imply a number without being one pass (`the only goal`, `a
minute later`); `one`, `first` and `second` pass unless a counted noun follows
(`one more shot` is refused), and `once` unless a counting word comes before it (`only
once`; "once he was through" passes, so does "shot once");
`the back four` is a line before any noun outside a fixed list ("their back four goals" is
refused, "the back four clearances" passes); a name that starts a sentence is checked only
against the league's other clubs and players, a name in lower case only against the league's,
so an invented or real name there passes; a reading's phrase is checked against the team named
before it, not against what the sentence says the team did ("Vellbridge Town take the lead"
citing their goal reading passes in a sentence about the other club too, if VEL is named last);
the result words are a list: the listed words are refused in their inflections and the derived
forms named above (`see … off` with at most 3 words between: "saw the brave young visiting side
off" passes), a synonym outside it passes ("thrashed", "sealed it", "came up short", "the
spoils"), an on-ball exception is not tied to its subject ("Vellbridge Town won the race"
passes), a number follows it directly only after a space ("won possession, 48%" passes), and
`edge of the` before a blanked phrase is a place, a window blanked in a claim of the last 5
minutes too ("on the edge of the last 5 minutes" passes), while some ordinary phrases are refused
("a lost ball", "he wins a challenge", "the shot edges past the post", "he is tied up", "a cutting
edge", "the edge of their box", "sees his shot deflect off the post": a retry, never a wrong
text); the order of the clubs around a score is not checked ("Saltreach FC 1–4 Quarrendale
Rovers" passes); a phrase passes when any claim around it passes the phrase rules, so a claim
nested in another one covers it ("Vellbridge Town are in the lead" inside a claim that also cites
a goal's minute); a recap's time rule is per claim and its window words are a list: a
whole-match reading passes in its own claim of the sentence that gives a goal's minute ("Adrien
Pellacourt scores at 5' and Corrowmere Athletic are chasing the game" as two claims) and beside
words outside the list that place it at a time ("after Adrien Pellacourt's goal", "at the
break", "early on"), and a shot's speed is of no time, so any reading may stand beside it.

Languages (`Language`, `LANGUAGES`): a Slovak text (a translation, `explain.translator`) is judged
by the same rules with Slovak lists: the readings' Slovak phrases (`stats.readings.PHRASES`),
numbers in words in any of their forms (`jeden`, `dva`, `dvakrát`, `prvý`, `druhý`, `polovica`,
`nula`, `jednu`, `dvaja`, `tretíkrát`; "z prvej" before no counted noun and "jeden na jedného" are
no claims), the vocabulary's phrases in other forms ("je navrchu", "naháňajú skóre", "k vedeniu",
"otvorenú hru", "pod veľkým tlakom") and the Slovak of the English judgement words (`vedie` but
"vedie k strele" or "vedie loptu", `vyrovnal`, `remíza`, `vyhrali` but "vyhrá loptu" or "vyhráva
súboj o loptu", `porazili`, "otvoril skóre", "úvodný gól", `zaostáva`, "je vzadu", `obrat`,
`bezgólový`, `body`, `prevaha`, "kontroluje hru", "lepší tím", `pokojný` but "pokojne zakončil",
`viac striel`, "väčší podiel lopty"; the result words also with "ne-" and in their other spellings:
`neporazený`, `nevyhrali`, `zvíťazil`, `remizovali`, `zremizovali`, "otvára skóre"; "na druhú žrď",
"druhú loptu", "v druhom polčase", "na vlastnej polovici" are no numbers), "posledných 5 minút" for
the window, other words for a window ("nedávno", "v tejto fáze", "polčas") and `č.`, `číslo`, `#` or
`dres` around a shirt number. Numerals are read alike, so `37,4` and "68. minúta" are no displays. A
name must stay as the league writes it: a declined name ("Pellacourta") is an unknown name. A
translation is also checked against its source (`check` with `source`): every numeral as the source
writes it, as often (`NUMERAL_CHANGED`), and the same name words of the match (`NAME_CHANGED`), in
at most `TRANSLATION_SLACK` times its source's limit of characters. Known limits: a language's text
is judged by its own lists only, so English words left in a Slovak text pass as words of no list
("They lead."); the Slovak lists are lists too: a synonym outside them passes, and some on-ball
phrases are refused ("porazí brankára", "po rýchlom obrate", "pod veľkým tlakom", a retry; "naháňa
loptu", "obratný", "pokojne premieňa" pass); the club named last before a phrase counts, which
Slovak word order meets less often ("Navrch má Corrowmere" is refused, a retry, and "Proti
Corrowmere má navrch Vellbridge Town" citing Corrowmere's reading passes); a sentence that says what
the source does not, with the same numerals and names, passes.
"""

import functools
import re
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from matchlens.events import EventType, frame_time
from matchlens.explain.state import Claim, Draft, MomentCase, Reason, ReasonCode, Verdict
from matchlens.facts import WINDOW_MS, Fact, Time, facts_at, match_facts
from matchlens.league import load_league
from matchlens.match import Match
from matchlens.stats.readings import PHRASES, VOCABULARY

MAX_TEXT = 1000  # characters of a narrative: an overlay line is a few sentences
MAX_CLAIMS = 12
RECAP_MAX_TEXT = 600  # characters of a match's recap: 3 to 5 sentences
TRANSLATION_SLACK = 1.25  # a translation may run this much longer than the limit of its source

# a numeral as a narrative writes it, longest form first; ASCII digits only, any other numeric
# character is unreadable
_NUMERAL = re.compile(
    r"(?P<clock>[0-9]+(?:\+[0-9]+)?:[0-9]{2})"  # 67:23, 45+2:13
    r"|(?P<stoppage>[0-9]+\+[0-9]+['’]?)"  # 45+3'
    r"|(?P<score>[0-9]+\s?[–—\-‑−/:]\s?[0-9]+|[0-9]+\s+to\s+[0-9]+)"  # 3–2, 3-2, 3/2, 3 to 2
    r"|(?P<plain>[0-9]+(?:\.[0-9]+)?(?:\s?%|st|nd|rd|th|['’])?)"  # 52%, 12.7, 68', 68th
)
_NUMBER_NAMES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_COUNTED = (
    r"(?:goals?|shots?|saves?|corners?|minutes?|attempts?|chances?|tackles?|fouls?|wins?"
    r"|points?|assists?|half-chances?)"
)
# what else a number before a noun may count: after `the back four` it is no line
_COUNTED_TOO = (
    r"(?:mins?|secs?|seconds?|times?|passes|games?|matches|yards?|metres?|meters?|efforts?"
    r"|crosses|touches|players?|men|hours?|days?|weeks?|months?|years?|seasons?|all)"
)
_NUMBER_WORDS = re.compile(
    r"\b(?:zero|nil|nought|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
    r"|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty"
    r"|fifty|sixty|seventy|eighty|ninety|hundred|thousand"
    r"|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth"
    r"|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth|thirtieth"
    r"|fortieth|fiftieth|sixtieth|seventieth|eightieth|ninetieth|hundredth"
    r"|twice|thrice|dozens?|brace|hat[- ]trick|treble|doubled|doubles|apiece|trio|triple"
    r"|quarter|hundreds|thousands|millions|tens|(?:two|three|four|five|ten)fold)\b"
    r"|\b(?:only|just|than|least|exactly|scored|struck|netted|saved) once\b"
    rf"|\b(?:one|first|second|single)[\s-]+(?:(?:more|fewer|less|extra|clear|league)\s+)?"
    rf"(?:{_COUNTED}|efforts?|strikes?|headers?|cross(?:es)?|touches)\b"  # not `first touch`
    r"|\bone[- ](?:nil|all|up|down)\b|\bby one\b|\ba (?:couple|pair) of\b"
    r"|(?<!first )(?<!second )\bhalf of\b",
    re.IGNORECASE,
)
# phrases with a number that make no claim about the match: blanked before numbers are read. A
# line (`the back four`) only after a determiner and before no counted noun: "hit back five
# minutes later" is a number
_PHRASES = re.compile(
    r"\b(?:six|6|18|eighteen)[- ]yard (?:box|line|area)\b|\bone[- ]two\b"
    r"|\b(?:50[- /]50|fifty[- ]fifty) (?:ball|challenge|tackle|header|duel)s?\b"
    r"|\b(?:the|a|their|his|its|our|flat|this|that)\s+"
    r"(?:back[- ](?:three|four|five)|front[- ](?:three|trio))\b"
    rf"(?![\s-]+(?:{_COUNTED}|{_COUNTED_TOO})\b)"
    r"|\b(?:final|attacking|defensive|middle) third\b|\bthird[- ]man (?:run|runner|combination)s?\b"
    r"|\bfourth official\b|\btwo[- ]footed\b|\bgame of two halves\b|\btriple saves?\b"
    r"|\bonce (?:again|more)\b|\bat once\b",
    re.IGNORECASE,
)
_WINDOW_MIN = WINDOW_MS // 60_000
_WINDOW_WORDS = (str(_WINDOW_MIN), *_NUMBER_NAMES[_WINDOW_MIN : _WINDOW_MIN + 1])
_WINDOW = re.compile(rf"\b(?:last|past)\s+(?:{'|'.join(_WINDOW_WORDS)})\s+minutes\b", re.I)
_SHIRT_BEFORE = re.compile(r"(?:\bNo\.|\bnumbers?|#|\bshirt)\s*$", re.IGNORECASE)
_SHIRT_AFTER = re.compile(r"\s*shirt\b", re.IGNORECASE)
_LOOK_BACK = 40  # characters a context check reads before a word or a number
_WORD = re.compile(r"[^\W\d_][\w'’-]*")
_NOT_A_SENTENCE_END = re.compile(r"\b(?:No|vs|v|St|[Ee]\.g|[Ii]\.e)\.$")
_CAPITALIZED = frozenset({"I", "No", "VAR"})  # capitalized words that are no names
_ENGLISH = frozenset({"Will"})  # league name words that also start English sentences
_GENERIC = frozenset({"Town", "Rovers", "Athletic", "FC"})  # club words that are English too
READING = "_reading"  # the name suffix of a reading fact (`facts`)


_SEP = r"[\s\-\u2010-\u2015\u2212]+"  # between words: spaces, a hyphen or any dash
_HYPHEN = r"[\-\u2010\u2011]"  # a hyphen joins words ("lead-up"); a dash ("lead—Malik") does not
# a window in other words than "last 5 minutes": no reading of the match so far belongs there
_RECENT = re.compile(
    r"\b(?:recent(?:ly)?|lately|of\s+late|this\s+spell|(?:last|past)\s+few\s+minutes"
    r"|(?:first|second)[\s-]+half|half[\s-]*time|(?:after|before)\s+the\s+break)\b",
    re.I,
)


_ON_THE_BALL = r"(?!\s+of\s+the\s+ball\b)"  # "on top of the ball" judges nothing


def _flexible(phrase: str) -> str:
    """A vocabulary phrase as a pattern: a hyphen, any dash or any space between its words."""
    words = r"\s+".join(re.escape(w) for w in re.split(r"[\s-]+", phrase))
    pattern = words.replace(r"\s+", _SEP) + rf"(?!{_HYPHEN}\w)"  # not "in the lead-up"
    return pattern + _ON_THE_BALL if phrase == "on top" else pattern


def _phrase_pattern(vocabulary: Mapping[str, str]) -> re.Pattern[str]:
    """Any phrase of `vocabulary`, the longest first, word-bounded, in any case."""
    phrases = sorted(set(vocabulary.values()), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(_flexible(p) for p in phrases) + r")\b", re.IGNORECASE)


_PHRASE = _phrase_pattern(VOCABULARY)
# a judgement of the score or the play that is no phrase of the vocabulary (phrases are blanked
# before this runs): the words the Analyst prompt bans, and the vocabulary in other forms
# where a player is, not who is winning: only these may follow "behind the" or "ahead of the"
# ("behind the defence", "ahead of the runner"; "behind the hosts" or "the Rovers" judges), also
# after a possessive ("behind the visitors' defence")
_PLACE = (
    r"(?:\w+['’]s?\s+)?(?-i:(?:defen[cs]e|defenders?|defensive\s+line|back\s+(?:line|four|three)"
    r"|line|ball|runner|wall|markers?|keeper|goalkeeper|striker|net|goal|box|area|post|centre-backs?|full-backs?"
    r"|play|move|attack|winger|forward)\b)"
)
_DIRECTION = r"(?:left|right|middle|centre|center|flank|wing|line|pitch|channel|front)\b"
# the result of the match is the score's to say, so "beat", "win", "lose" and "draw" judge,
# but not what a player beats, wins or loses on the ball ("beats the keeper", "wins a corner",
# "lost the ball") or what a shot draws ("draws a fine save")
# after an article or a possessive only: "beats defenders" or "won ball after ball" judges a team
_ARTICLE = r"(?:the|a|an|his|her|their)\s+"
_BEATEN = (
    r"(?:keeper|goalkeeper|defenders?|defence|marker|man|last\s+man|wall|offside\s+trap|press"
    r"|full-back|centre-back)\b"
)
# what one player wins or loses: one ball, duel or tackle, never the possession battle, the duels
# or a penalty shoot-out
_WON = (
    r"(?:(?:loose|second|aerial)\s+)?(?:ball|corner|free[\s‑-]+kick|throw-in|header|duel|tackle"
    r"|foul|race|flick|marker|penalty(?!\s+shoot)|goal\s+kick|footing)\b"
)
_DRAWN = r"(?:save|foul|block|tackle|stop|keeper|goalkeeper)\b"
# a place with an edge: "the edge of the box" is a place, "the edge of the contest" a judgement
# ("the six-yard box" is blanked before the judgements are read, as a phrase with a number)
_PLACE_EDGED = r"(?:box|area|penalty\s+area|pitch|d)\b"
_JUDGEMENT = re.compile(
    rf"""\b(?:
        (?:leads|leading|led)(?!\s+(?:to\s+[^\W\d]|the\s+line\b))|lead(?:ers?)?(?!{_HYPHEN}up\b)
        |ahead(?!\s+of\s+(?:him\b|her\b|(?:the|his|their)\s+{_PLACE}))|in\s+front(?!\s+of\b)
        |equali[sz]\w*|openers?|winners?|come{_HYPHEN}?backs?|all\s+square|goalless|deadlock
        |open(?:s|ed|ing)?\s+the\s+scoring|hits?\s+back|restor\w*|cancel\w*\s+out
        |(?:better|brighter|stronger)\s+(?:side|team)|against\s+the\s+run\s+of\s+play|deficit
        |upper\s+hand|(?:narrow|close)\w*\s+the\s+gap|back\s+in\s+the\s+game
        |back\s+on\s+(?:\w+\s+)?terms|fight\w*(?:{_SEP})?back|in\s+charge(?!\s+of\s+the\s+(?:box|area)\b)
        |peg\w*\s+(?:\w+\s+){{0,2}}back
        |advantage(?!\s+of\b)|dominan(?:t|ce)|dominat\w*|in\s+control(?!\s+of\s+the\s+ball\b)
        |(?:take|takes|took|taking)\s+control(?!\s+of\s+the\s+ball\b)|in\s+command
        |on\s+the\s+(?:front|back)\s+foot
        |outplay\w*|superior|chaotic|calm(?!\s+finish)|outsh(?:oot|oots|ooting|ot)
        |level(?:s|led|ling|ed|ing)?(?!{_SEP}of\b)|trail\w*
        |(?<!tackle\sfrom\s)(?<!challenge\sfrom\s)(?<!\bin\s)behind
        (?!\s+(?:the|his|their|its|a)\s+{_PLACE})
        |a\s+goal\s+(?:up|down)
        |(?:pull|get|got|claw|grab|nick|snatch)\w*{_SEP}(?:one|a\s+goal){_SEP}back
        |pinn(?:ed|ing){_SEP}back|evenly{_SEP}match\w*|on{_SEP}top{_ON_THE_BALL}
        |end{_SEP}to{_SEP}end|share\s+of\s+the\s+ball
        |(?:un)?beat(?:s|en|ing|able|ably)?(?!\s+{_ARTICLE}{_BEATEN}(?!\s+[0-9]))|beatings
        |(?:win|wins|winning|won|lose|loses|losing|lost)(?!['’]t\b|\s+(?:back\s+)?(?:possession\b
            (?!{_SEP}(?:battle|war|game|contest|stakes)s?\b|\s+[0-9])|{_ARTICLE}{_WON}
            (?!\s+[0-9])|it\s+back\b(?!\s+[0-9])))
        |(?:un)?winnable|unwon|winnings|winningest|outw[io]n\w*|los(?:able|ings)
        |loss(?:es)?|losers?|winless|(?:un)?defeat\w*|victor\w*|triumph\w*|stalemat\w*
        |overc[ao]m\w*|prevail\w*|(?:re)?(?:tying|ti(?:e|es|ed))
        |(?:re)?(?:draw|draws|drew|drawn|drawing)(?!\s+(?:a|an|another|the)\s+(?:\w+\s+)?{_DRAWN}(?!\s+[0-9]))
        |drawings|points|(?<!\bat\sthis\s)(?<!\bat\sthat\s)point(?![\s‑-]+blank)
        |s(?:ee|ees|eeing|aw|een){_SEP}(?:[\w'’]+{_SEP}){{0,3}}?off(?!\s+(?:his|her|their|the)\s+line\b)
        |edg(?:e|es|ed|ing)(?!\s+of\s+the\s+(?:{_PLACE_EDGED}|\s))  # or a blanked place
    )\b
    |\b(?:more|fewer|less|most)\b(?:\W+\w+){{0,3}}?\W+(?:ball|possession|shots?|passes|chances?)\b
    |(?:(?<=[0-9%]\s)|(?<=[0-9%]))(?:up|down)\b(?!\s+(?:the\s+)?{_DIRECTION})  # 2–1 up, not
    # "67:23 down the right" or "No. 9 up front"
    |\b(?:up|down)(?=\s[0-9])  # down 1–3
    """,
    re.IGNORECASE | re.VERBOSE,
)

Span = tuple[int, int]


@dataclass(frozen=True)
class Language:
    """What the Guard reads in the language of a text: the readings' phrases, phrases with a
    number that make no claim, numbers in words, judgements without a reading, the window of the
    last minutes (and other words for a window) and a shirt number's context. Numerals are read
    alike in every language: digits only, in the forms the engine displays."""

    code: str
    phrases: Mapping[str, str]  # a reading's code → its phrase in this language
    phrase: re.Pattern[str]
    fixed: re.Pattern[str]
    number_words: re.Pattern[str]
    judgement: re.Pattern[str]
    window: re.Pattern[str]
    window_text: str  # how a claim names the window of the last minutes
    recent: re.Pattern[str]
    recent_text: str  # examples of other words for a window, for a retry's hint
    shirt_before: re.Pattern[str]
    shirt_after: re.Pattern[str]
    shirt_text: str  # what a shirt number needs before it, for a retry's hint

    def phrase_of(self, fact: Fact) -> str:
        """A reading's phrase in this language (its `value` is the code)."""
        return self.phrases.get(str(fact.value), fact.display)


ENGLISH = Language(
    "en",
    VOCABULARY,
    _PHRASE,
    _PHRASES,
    _NUMBER_WORDS,
    _JUDGEMENT,
    _WINDOW,
    f"last {_WINDOW_MIN} minutes",
    _RECENT,
    "'recently', 'in this spell'",
    _SHIRT_BEFORE,
    _SHIRT_AFTER,
    "No.",
)

# Slovak: a caption's translation (M5). The same numerals; numbers in words in any of their forms
# (cases, genders, `dvakrát`, `polovica`), the vocabulary's words in other forms and the result in
# words; a club or player name only in the form the league gives, so never declined
_SK_NUMBER_NAMES = ("nula", "jeden", "dva", "tri", "štyri", "päť", "šesť", "sedem", "osem")
_SK_ENDS = r"(?:ý|á|é|ú|ého|ej|ému|om|ým|ou|í|ých|ými|ýkrát)"  # an ordinal's forms
_SK_NUMBER_WORDS = re.compile(
    r"\b(?:nul(?:a|y|e|u|ou)|jed(?:en|na|nu|no|ného|nej|nému|nom|ným|nou|ni|ny|ných|nými)"
    r"|jedenkrát|dv(?:a|aja|e|och|om|oma|akrát|ojic\w*|ojk\w*)|\w*(?:dvoj|troj)násob\w*"
    r"|tr(?:i|aja|och|om|omi|ikrát|ojic\w*|ojk\w*)|štyr(?:i|ia|och|om|mi|ikrát)"
    r"|päť|šesť|sedem|osem|deväť|desať|\w+násť|\w+dsať|\w+desiat|sto|tisíc\w*|milión\w*"
    r"|(?:päť|šesť|sedem|osem|deväť|desať)krát"
    rf"|prv{_SK_ENDS}|druh{_SK_ENDS}|štvrt(?:{_SK_ENDS}|in\w*)"
    r"|tret(?:í|ia|ie|iu|ieho|ej|iemu|om|ím|ích|ími|íkrát)"
    r"|piat\w*|šiest\w*|siedm\w*|ôsm\w*|deviat\w*|desiat\w*"
    r"|polovic\w*|polovičn\w*|pol|hetrik\w*|hattrick\w*|dublet\w*|pár)\b"
    r"|\b(?:len|iba|práve|presne|aspoň|ani)\s+raz\b",
    re.IGNORECASE,
)
# what a number before a noun counts: "z prvej" is a first-time shot only before none of them
_HRA = r"hr(?:a|u|y|e|ou)\b"  # the game ("hra"), not a player ("hráč")
# what a number before a noun counts (nouns, not the verbs that share a stem: "z prvej strelil"):
# "z prvej" is a first-time shot only before none of them, even with adjectives in between
_SK_COUNTED = (
    r"(?:gól(?:y|u|ov|om|mi)?|strel(?:a|y|u|e|ou|ami)|striel|šanc(?:a|e|u|ou|í)|príležitos\w*"
    r"|minút(?:a|y|u|e|ou)?|zákrok\w*|rohov\w*|kop(?:y|u|ov|om)?|pokus\w*|akci(?:a|e|u|ou|í)"
    r"|prihrávk\w*|lopt(?:a|y|u|e|ou)|polčas\w*|zápas\w*|tím\w*|hráč\w*|bod(?:y|ov|u)?)"
)
# phrases with a number word that make no claim: blanked before numbers are read (the window
# words around them are read on the raw text, so a half still names a window)
_SK_FIXED = re.compile(
    rf"\bjeden\s+na\s+jedného\b|\bz\s+prvej\b(?!\s+(?:\w+ej\s+){{0,2}}{_SK_COUNTED}\b)"
    r"|\bprv(?:ý|ým|ého|om)\s+dotyk\w*|\bštvrt(?:ý|ého|ým|om)\s+rozhodc\w*|\bv\s+prvom\s+rade\b"
    r"|\bna\s+druh(?:ú|ej|ou)\s+(?:žrď|tyč|stran\w*|polovic\w*)|\bna\s+vlastn\w*\s+polovic\w*"
    r"|\bdruh(?:á|ú|ej|ou)\s+lopt(?:a|y|u|e|ou)\b|\b(?:v|cez)\s+(?:prv|druh)\w*\s+polčas\w*"
    r"|\bo\s+pár\s+sekúnd\b",
    re.IGNORECASE,
)
_SK_JUDGEMENT = re.compile(
    rf"""\b(?:
        veden[ií]\w*(?!\s+lopt\w*)|(?:ne)?ved(?:ie|ú|úci\w*)(?!\s+(?:k|ku|loptu)\b)|viedl?\w*
        |(?:ne)?vyrovn\w*|náskok\w*|zníž\w*|zniž\w*|nerozhodn\w*|(?:ne)?z?rem[ií]z\w*
        |(?:ne)?vyhr\w*(?!\s+(?:(?:hlavičkový\s+)?súboj\s+o\s+lopt\w*|hlavičkový\s+súboj
            |loptu(?!\s+za\s+loptou))\b)
        |výhr\w*|z?víťaz\w*|(?:ne)?prehr\w*|(?:ne)?poraz\w*|porážk\w*|zdola\w*
        |domin\w*|pod\s+kontrolou|kontrol(?:uj|ov)\w*\s+(?:\w+\s+)?{_HRA}|chaotick\w*
        |pokojn(?:ý|á|é|ého|ej|ému|om|ým|ou|í|ých|ými)|prevah\w*|lepš\w*\s+(?:tím|mužstv)\w*
        |otv(?:or|ár)\w*\s+(?:\w+\s+)?skóre|úvodn\w*\s+gól\w*|obrat(?!n)\w*|bezgólov\w*
        |body|bodov|zaostáv\w*|zaostal\w*|(?:je|sú|bol\w*)\s+(?:\w+\s+)?vzadu
        |navrch\w+|naháň\w*\s+(?:\w+\s+)?(?:skór\w*|výsled\w*|vyrovnan\w*)
        |otvoren\w*\s+{_HRA}|{_HRA}\s+(?:je|bola|bude)\s+otvoren\w*
        |trpezliv\w*\s+rozohráv\w*|rovnomern\w*\s+temp\w*
        |podiel\w*\s+lopt\w*|pod\s+(?:\w+\s+)?tlak\w*
    )\b
    |\b(?:viac|menej|najviac|najmenej)\b(?:\W+\w+){{0,3}}?\W+
        (?:lopt\w*|držani\w*|str(?:i?e)l\w*|prihráv\w*|šanc\w*)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
_SK_WINDOW_WORDS = (str(_WINDOW_MIN), _SK_NUMBER_NAMES[_WINDOW_MIN])
_SK_WINDOW = re.compile(
    rf"\b(?:posledných|ostatných)\s+(?:{'|'.join(_SK_WINDOW_WORDS)})\s+minút(?:ach)?\b", re.I
)
_SK_RECENT = re.compile(
    r"\b(?:nedávn\w*|v\s+poslednom\s+čase|v\s+tejto\s+fáze"
    r"|(?:posledných|ostatných)\s+(?:pár|niekoľk\w*)\s+minút\w*"
    r"|(?:prv|druh)\w*\s+polčas\w*|polčas\w*|po\s+prestávke|pred\s+prestávkou)\b",
    re.I,
)
SLOVAK = Language(
    "sk",
    PHRASES["sk"],
    _phrase_pattern(PHRASES["sk"]),
    _SK_FIXED,
    _SK_NUMBER_WORDS,
    _SK_JUDGEMENT,
    _SK_WINDOW,
    f"posledných {_WINDOW_MIN} minút",
    _SK_RECENT,
    "'nedávno', 'v tejto fáze'",
    re.compile(r"(?:\bč\.|\bčísl\w*|#|\bdres\w*)\s*$", re.IGNORECASE),
    re.compile(r"\s*na\s+dres\w*\b", re.IGNORECASE),
    "č.",
)
LANGUAGES = {language.code: language for language in (ENGLISH, SLOVAK)}


@dataclass(frozen=True)
class Evidence:
    """What the engine knows at a moment: its facts by id, the events up to the moment, which
    frame ids are frames of the match up to then, the name words a narrative may use, and the
    league's other names, refused anywhere."""

    facts: Mapping[str, Fact]
    event_ids: frozenset[str]
    is_frame: Callable[[str], bool]
    names: frozenset[str]
    foreign_names: frozenset[str] = frozenset()
    teams: Mapping[str, str] = field(default_factory=dict)  # a club or player name → its team


def moment_evidence(match: Match, case: MomentCase) -> Evidence:
    """The engine's evidence for `case`: `facts_at` its end, the events up to then. A case whose
    facts are not the engine's is a bug of the pipeline, not a draft to judge: ValueError."""
    meta = match.meta
    if case.match_id != meta.match_id:
        raise ValueError(f"moment {case.moment_id!r} is not of match {meta.match_id}")
    facts = {f.fact_id: f for f in facts_at(match, case.period, case.end_ms)}
    return _evidence(match, case, facts)


def recap_evidence(match: Match, case: MomentCase, whole: Sequence[Fact] | None = None) -> Evidence:
    """The engine's evidence for a match's recap at full time: the whole match's facts
    (`match_facts`, or `whole` if already computed), but a half's, and of each goal's instant its
    minute and the score it made; every event and frame of the match. ValueError as
    `moment_evidence`."""
    meta = match.meta
    if case.match_id != meta.match_id:
        raise ValueError(f"moment {case.moment_id!r} is not of match {meta.match_id}")
    whole = match_facts(match) if whole is None else whole
    if any(f.match_id != meta.match_id for f in whole):
        raise ValueError(f"facts of another match than {meta.match_id}")
    # a half's facts would judge the play in a claim that names no window: the match's only
    facts = {f.fact_id: f for f in whole if _scope(f) not in ("p1", "p2")}
    for goal in (e for e in match.events if e.type is EventType.GOAL):
        facts |= {f.fact_id: f for f in goal_facts(match, (goal.period, goal.clock_ms))}
    return _evidence(match, case, facts)


def goal_facts(match: Match, at: Time) -> list[Fact]:
    """The facts a recap may cite of a goal's instant: its minute and the score it made."""
    return [
        f
        for f in facts_at(match, *at)
        if (f.name, _scope(f)) in (("minute", "at"), ("score", "to"))
    ]


def _evidence(match: Match, case: MomentCase, facts: dict[str, Fact]) -> Evidence:
    """`facts` as the evidence of `case`, after checking the case's copies against them; the
    events and frames of the match up to the case's end."""
    meta = match.meta
    now = (case.period, case.end_ms)
    for shown in case.facts:
        fact = facts.get(shown["fact_id"])
        if fact is None or fact.display != shown["display"]:
            raise ValueError(
                f"moment {case.moment_id!r}: {shown['fact_id']} = {shown['display']!r} is not "
                f"the engine's fact at {case.display_clock}"
            )
    events = frozenset(e.event_id for e in match.events if (e.period, e.clock_ms) <= now)

    def is_frame(frame_id: str) -> bool:
        try:
            match_id, period, clock_ms = frame_time(frame_id)
            if match_id != meta.match_id or (period, clock_ms) > now:
                return False
            match.frame_at(period, clock_ms)
        except ValueError:
            return False
        return True

    names = match_names(match)
    return Evidence(
        facts, events, is_frame, names, _league_words() - names - _ENGLISH, team_names(match)
    )


def match_names(match: Match) -> frozenset[str]:
    """Words of the names a narrative of this match may use: its 22 players, its two clubs
    (name, short name, city) and the league."""
    league = load_league()
    meta = match.meta
    lineup = set(meta.home_lineup + meta.away_lineup)
    texts = [league.name]
    for club in league.clubs:
        if club.id in (meta.home, meta.away):
            texts += [club.name, club.short_name, club.city]
            texts += [p.name for p in club.players if p.id in lineup]
    return frozenset(_WORD.findall(" ".join(texts)))


def team_names(match: Match) -> dict[str, str]:
    """The names a claim may give a team by, each with its team: the club's name, short name
    and city, and each lineup player's full name and, if no other player of the match has it,
    surname. A club's name comes first among its team's names (the Guard's hints use it)."""
    league, meta = load_league(), match.meta
    lineup = set(meta.home_lineup + meta.away_lineup)
    names: dict[str, str] = {}
    players = [(p, c.id) for c in league.clubs for p in c.players if p.id in lineup]
    surnames = [p.name.split()[-1] for p, _ in players]
    for club in league.clubs:
        if club.id in (meta.home, meta.away):
            names |= dict.fromkeys((club.name, club.short_name, club.city), club.id)
    for (player, team), surname in zip(players, surnames, strict=True):
        names[player.name] = team
        if surnames.count(surname) == 1:
            names[surname] = team
    return names


@functools.cache
def _league_words() -> frozenset[str]:
    league = load_league()
    texts = [league.name]
    for club in league.clubs:
        texts += [club.name, club.short_name, club.city, *(p.name for p in club.players)]
    return frozenset(_WORD.findall(" ".join(texts)))


def judge(case: MomentCase, evidence: Evidence) -> Verdict:
    """The Guard's verdict on the attempt waiting for it: the Analyst's last attempt, or once the
    case is a narrative, the last attempt of its rendition being written, or once every rendition
    is closed, of its translation being written (judged in its language, against its source)."""
    rendition = None if case.is_open else case.pending_rendition
    translation = None if case.is_open or rendition else case.pending_translation
    attempts = (rendition or translation or case).attempts
    if not attempts or attempts[-1].verdict is not None:
        raise ValueError(f"moment {case.moment_id!r} has no attempt waiting for the Guard")
    attempt = attempts[-1]
    if attempt.draft is None:
        detail = f"the attempt failed ({attempt.error.code}): {attempt.error.detail}"
        return Verdict(False, (Reason(ReasonCode.NO_DRAFT, detail),))
    if translation is not None:
        source = case.source(translation)
        return check(attempt.draft, case, evidence, translation.lang, source)
    return check(attempt.draft, case, evidence)


def check(
    draft: Draft,
    case: MomentCase,
    evidence: Evidence,
    lang: str = ENGLISH.code,
    source: Draft | None = None,
) -> Verdict:
    """Every rule of the module docstring, on one draft written in `lang` (a key of
    `LANGUAGES`). The same draft gives the same reasons in the same order; reordering its claims
    changes only the claim indices of the reasons. A recap's text has `RECAP_MAX_TEXT` characters
    at most, a moment's `MAX_TEXT`. With `source`, the draft is its translation: it may be
    `TRANSLATION_SLACK` times as long, and it keeps every numeral of the source byte for byte, as
    often as the source has it, and the same name words of the match."""
    language = LANGUAGES[lang]
    text = draft.text
    max_text = RECAP_MAX_TEXT if case.is_recap else MAX_TEXT
    if source is not None:  # Slovak runs longer than English
        max_text = int(max_text * TRANSLATION_SLACK)
    if len(text) > max_text or len(draft.claims) > MAX_CLAIMS:
        detail = f"at most {max_text} characters and {MAX_CLAIMS} claims"
        return Verdict(False, (Reason(ReasonCode.TOO_LONG, detail),))
    reasons: list[Reason] = []
    if not draft.claims:
        reasons.append(Reason(ReasonCode.NO_CLAIMS, "a narrative needs claims with evidence"))
    spans: dict[int, list[Span]] = {}
    cited: dict[int, list[Fact]] = {}
    for i, claim in enumerate(draft.claims):
        found = [m.span() for m in re.finditer(re.escape(claim.text), text)]
        spans[i] = found if claim.text.strip() else []
        if not spans[i]:
            detail = "each claim's text must appear word for word in the narrative"
            reasons.append(Reason(ReasonCode.CLAIM_NOT_IN_TEXT, detail, claim=i))
        cited[i] = [evidence.facts[f] for f in claim.fact_ids if f in evidence.facts]
        reasons += _evidence_reasons(i, claim, cited[i], case, evidence)
        if any(_scope(f) == "last5" for f in cited[i]) and not language.window.search(claim.text):
            detail = f"a fact of the last {_WINDOW_MIN} minutes needs '{language.window_text}'"
            reasons.append(Reason(ReasonCode.SCOPE_NOT_NAMED, detail, claim=i))

    if case.is_recap and not any(
        _states_final_score(c, cited[i]) for i, c in enumerate(draft.claims)
    ):
        detail = (
            "a recap states the final score: write the display of the whole match's score fact "
            "in a claim that cites it"
        )
        reasons.append(Reason(ReasonCode.NO_FINAL_SCORE, detail))

    def covering(span: Span) -> list[int]:
        return [
            i for i, found in spans.items() if any(a <= span[0] <= span[1] <= b for a, b in found)
        ]

    for m in language.phrase.finditer(text):
        reasons += _phrase_reasons(m, spans, cited, text, evidence, language)
    blanked = [m.span() for m in language.fixed.finditer(text)]
    blanked += [m.span() for m in language.phrase.finditer(text)]
    for m in language.window.finditer(text):
        if any(_scope(f) == "last5" for i in covering(m.span()) for f in cited[i]):
            blanked.append(m.span())
    readable = _blank(text, blanked)
    for m in _NUMERAL.finditer(readable):
        token, around = _normal(m), covering(m.span())
        mine = [f for i in around for f in cited[i]]
        if not around:
            detail = f"{token} is in no claim: put every number into a claim that cites its fact"
            reasons.append(Reason(ReasonCode.NUMBER_OUTSIDE_CLAIM, detail, token))
        elif not any(_backs(f, token, text, m.span(), language) for f in mine):
            detail = _not_cited(token, text, m.span(), mine, evidence, language)
            reasons.append(Reason(ReasonCode.NUMBER_NOT_CITED, detail, token, min(around)))
    for m in language.number_words.finditer(readable):
        detail = (
            f"{m.group()!r} is a number in words: use digits only where a cited fact displays "
            "the number, otherwise reword without it"
        )
        reasons.append(Reason(ReasonCode.NUMBER_WORD, detail, m.group()))
    for m in language.judgement.finditer(readable):
        detail = (
            f"{m.group()!r} judges the score or the play: only a cited reading's phrase may do "
            "that, written as its 'write as'; otherwise state the cited numbers"
        )
        reasons.append(Reason(ReasonCode.JUDGEMENT_WORD, detail, m.group()))
    for char in sorted({c for c in readable if c.isnumeric() and c not in "0123456789"}):
        detail = f"{char!r} is a number the Guard cannot read: write numbers in digits 0-9"
        reasons.append(Reason(ReasonCode.UNREADABLE_NUMBER, detail, char))
    for name in _unknown_names(text, evidence):
        detail = (
            f"{name!r} is no player of the lineups and no club of this match: use their names, "
            "and lower case for any word that is no name"
        )
        reasons.append(Reason(ReasonCode.UNKNOWN_NAME, detail, name))
    if source is not None:
        reasons += _kept_reasons(text, source.text, evidence)
    # one reason per offending token, whichever claim it was found in first
    unique: dict = {}
    for r in reasons:
        unique.setdefault((r.code, r.token) if r.token is not None else r, r)
    return Verdict(not unique, tuple(unique.values()))


def _evidence_reasons(
    i: int, claim: Claim, cited: list[Fact], case: MomentCase, evidence: Evidence
) -> Iterator[Reason]:
    for fact_id in claim.fact_ids:
        if fact_id not in evidence.facts:
            detail = f"{fact_id} is no fact of this match at {case.display_clock}"
            yield Reason(ReasonCode.UNKNOWN_FACT, detail, fact_id, i)
    if not claim.event_ids and not claim.frame_ids:
        yield Reason(ReasonCode.NO_EVIDENCE, "a claim needs event or frame ids", claim=i)
    events = set(case.trigger_ids).union(*(f.event_ids for f in cited))
    frames = set().union(*(f.frame_ids for f in cited))
    for event_id in claim.event_ids:
        if event_id not in evidence.event_ids:
            detail = f"{event_id} is no event of this match up to {case.display_clock}"
            yield Reason(ReasonCode.UNKNOWN_EVENT, detail, event_id, i)
        elif event_id not in events:
            detail = f"{event_id} is evidence of no cited fact and no trigger of the moment"
            yield Reason(ReasonCode.FOREIGN_ID, detail, event_id, i)
    for frame_id in claim.frame_ids:
        if not evidence.is_frame(frame_id):
            detail = f"{frame_id} is no frame of this match up to {case.display_clock}"
            yield Reason(ReasonCode.UNKNOWN_FRAME, detail, frame_id, i)
        elif frame_id not in frames:
            detail = f"{frame_id} is evidence of no cited fact"
            yield Reason(ReasonCode.FOREIGN_ID, detail, frame_id, i)


def _kept_reasons(text: str, source: str, evidence: Evidence) -> Iterator[Reason]:
    """Reasons against a translation that does not keep its source's numerals byte for byte (as
    often as the source has each) or its name words of the match."""
    mine, theirs = (Counter(m.group() for m in _NUMERAL.finditer(t)) for t in (text, source))
    for token in sorted((theirs - mine).keys()):
        detail = f"{token} of the source is missing: keep every numeral as the source writes it"
        yield Reason(ReasonCode.NUMERAL_CHANGED, detail, token)
    for token in sorted((mine - theirs).keys()):
        detail = f"{token} is no numeral of the source: copy the source's numerals byte for byte"
        yield Reason(ReasonCode.NUMERAL_CHANGED, detail, token)
    mine, theirs = (_name_words(t, evidence) for t in (text, source))
    for name in sorted(theirs - mine):
        detail = f"{name!r} of the source is missing: keep every name as the source writes it"
        yield Reason(ReasonCode.NAME_CHANGED, detail, name)
    for name in sorted(mine - theirs):
        detail = f"{name!r} is no name of the source: add no name"
        yield Reason(ReasonCode.NAME_CHANGED, detail, name)


def _name_words(text: str, evidence: Evidence) -> set[str]:
    """The words of `text` that are words of a name of the match (a possessive's `'s` dropped)."""
    words = (re.sub(r"['’]s?$", "", m.group()) for m in _WORD.finditer(text))
    return {w for w in words if w in evidence.names}


def _phrase_reasons(
    m: re.Match[str],
    spans: Mapping[int, list[Span]],
    cited: Mapping[int, list[Fact]],
    text: str,
    evidence: Evidence,
    language: Language = ENGLISH,
) -> Iterator[Reason]:
    """Reasons against a vocabulary phrase at `m`: none if a claim around it cites a reading
    that shows it in `language`, of the team named last before it in that claim (or of no
    team)."""
    phrase, key = m.group(), _phrase_key(m.group())
    around = [
        (i, a, b) for i, found in spans.items() for a, b in found if a <= m.start() <= m.end() <= b
    ]
    if not around:
        detail = (
            f"{phrase!r} judges a number: put it into a claim that cites the reading showing it"
        )
        yield Reason(ReasonCode.PHRASE_OUTSIDE_CLAIM, detail, phrase)
        return
    teams, windows, times = [], [], []
    for i, start, end in around:
        windowed = bool(language.window.search(text, start, end))
        recent = bool(language.recent.search(text, start, end))
        # a recap's claim speaks of the whole match or of one goal's instant, never of both
        instants = {_instant(f) for f in cited[i] if _scope(f) in ("at", "to")}
        whole = any(_scope(f) == "match" for f in cited[i])
        for fact in cited[i]:
            if fact.name.endswith(READING) and _phrase_key(language.phrase_of(fact)) == key:
                last5 = _scope(fact) == "last5"
                if last5 != windowed or (recent and not last5):  # a reading of another window
                    windows.append(fact)
                    continue
                if (_scope(fact) == "match" and instants) or (
                    _scope(fact) in ("at", "to") and (whole or instants != {_instant(fact)})
                ):
                    times.append(fact)
                    continue
                named = _last_team(text[start : m.start()], evidence.teams)
                if fact.team is None or fact.team == named:
                    return
                teams.append(fact.team)
    if teams:
        clubs = [next((n for n, t in evidence.teams.items() if t == team), team) for team in teams]
        detail = (
            f"{phrase!r} is the reading of {' or '.join(dict.fromkeys(clubs))}: name that club "
            "last before the phrase in the claim, with no other club or player name in between"
        )
    elif times:
        detail = (
            f"{phrase!r} is cited from {_what(times[0])}, but the claim also cites a fact of "
            "another time: a reading of the whole match and a fact of a goal's instant (its "
            "minute, the score it made) go into separate claims, and a goal's reading only beside "
            "the minute and the score of that same goal"
        )
    elif windows:
        detail = (
            f"{phrase!r} is cited from {_what(windows[0])}, whose window is not the claim's: a "
            f"reading of the last {_WINDOW_MIN} minutes needs '{language.window_text}' in its "
            "claim and any other reading a claim without it, and without other words for a window "
            f"({language.recent_text}); put them into separate claims"
        )
    else:
        shown = sorted(
            _what(f)
            for f in evidence.facts.values()
            if f.name.endswith(READING) and _phrase_key(language.phrase_of(f)) == key
        )
        detail = (
            f"no reading of the moment shows {phrase!r}: drop the phrase"
            if not shown
            else f"{phrase!r} is not shown by the readings this claim cites; at this moment it is "
            f"the {' or the '.join(shown[:3])}. Cite such a reading only if the sentence says "
            "exactly that, of the same club and window, otherwise drop the phrase"
        )
    yield Reason(ReasonCode.PHRASE_NOT_CITED, detail, phrase, min(i for i, _, _ in around))


def _states_final_score(claim: Claim, cited: list[Fact]) -> bool:
    """Whether `claim` cites the whole match's score and writes it in a form the Guard reads."""
    finals = [f for f in cited if f.name == "score" and _scope(f) == "match"]
    tokens = {_normal(m) for m in _NUMERAL.finditer(claim.text)}
    return any(tokens & _forms(f) for f in finals)


def _phrase_key(text: str) -> str:
    return re.sub(_SEP, " ", text.strip().lower())


def _last_team(before: str, teams: Mapping[str, str]) -> str | None:
    """The team of the last club or player name in `before`, longest name first; None if none."""
    if not teams:
        return None
    names = sorted(teams, key=len, reverse=True)
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b")
    found = list(pattern.finditer(before))
    return teams[found[-1].group()] if found else None


def _not_cited(
    token: str,
    text: str,
    span: Span,
    cited: list[Fact],
    evidence: Evidence,
    language: Language = ENGLISH,
) -> str:
    """The retry hint for a number no cited fact backs. It says what a fact showing the number
    counts and allows citing it only if the sentence states exactly that: the Guard cannot see
    what the sentence says."""
    for fact in cited:
        if token in _forms(fact) and (missing := _missing_context(fact, text, span, language)):
            return f"{token} is the {_what(fact)}, but {missing}"
    shown = sorted({_what(f) for f in evidence.facts.values() if token in _forms(f)})
    if not shown:
        return f"no fact of the moment shows {token}: drop the number"
    return (
        f"{token} is not shown by the facts this claim cites; at this moment {token} is the "
        f"{' or the '.join(shown[:3])}. Cite such a fact only if the sentence states exactly "
        "that, otherwise drop the number"
    )


def _what(fact: Fact) -> str:
    """What a fact counts, for a retry hint: `goals of cor [m7/goals/to-1-258000/cor]`."""
    who = fact.player or fact.team
    name = fact.name.replace("_", " ")
    return f"{name} of {who} [{fact.fact_id}]" if who else f"{name} [{fact.fact_id}]"


def _backs(fact: Fact, token: str, text: str, span: Span, language: Language = ENGLISH) -> bool:
    """Whether `fact` is what the numeral `token` at `span` of `text` shows."""
    return token in _forms(fact) and _missing_context(fact, text, span, language) is None


def _missing_context(fact: Fact, text: str, span: Span, language: Language = ENGLISH) -> str | None:
    """What the text lacks around a numeral that shows `fact`, or None."""
    if fact.name == "shirt_number":
        before = text[max(0, span[0] - _LOOK_BACK) : span[0]]
        if not (language.shirt_before.search(before) or language.shirt_after.match(text, span[1])):
            return f"a shirt number needs '{language.shirt_text}' before it"
    unit = re.compile(rf"\s?{re.escape(fact.unit)}(?![\w/])")
    if fact.unit not in fact.display and not unit.match(text, span[1]):  # "" is in any display
        return f"this number needs its unit {fact.unit!r} right after it"  # 12.7 km
    return None


def _forms(fact: Fact) -> set[str]:
    """How a narrative may write a fact: its display; a minute also as an ordinal (68' → 68th),
    a clock also without its leading zero (09:05 → 9:05)."""
    forms = set(numerals(fact.display))
    if fact.name == "minute" and (minute := fact.display.rstrip("'")).isdigit():
        forms.add(ordinal(int(minute)))
    if fact.name == "clock" and fact.display.startswith("0"):
        forms.add(fact.display[1:])
    return forms


def ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st, 22nd, 23rd, 101st, 111th."""
    suffix = "th" if n % 100 in (11, 12, 13) else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _scope(fact: Fact) -> str:
    """The scope part of a fact id before its stamp: `last5`, `to`, `at`, `match`, `p1`."""
    parts = fact.fact_id.split("/")
    return parts[2].split("-")[0] if len(parts) == 4 else ""


def _instant(fact: Fact) -> str:
    """The instant an `at` or `to` fact is of, from its id: `1-258931` of `at-1-258931`. Not its
    `end`: a flow fact so far ends at the last spell it counts, before the instant."""
    return fact.fact_id.split("/")[2].partition("-")[2]


def numerals(text: str) -> list[str]:
    """The numerals of a text, normalized as displays are written (`52 %` → `52%`, `3-2` and
    `3:2` and `3 to 2` → `3–2`, `68’` → `68'`)."""
    return [_normal(m) for m in _NUMERAL.finditer(text)]


def _normal(m: re.Match[str]) -> str:
    if m.lastgroup == "score":
        return re.sub(r"\s*(?:to|[–—\-‑−/:])\s*", "–", m.group())
    return re.sub(r"\s", "", m.group()).replace("’", "'")


def _blank(text: str, spans: list[Span]) -> str:
    """`text` with the given spans replaced by spaces: positions stay where they were."""
    chars = list(text)
    for a, b in spans:
        chars[a:b] = " " * (b - a)
    return "".join(chars)


def _unknown_names(text: str, evidence: Evidence) -> Iterator[str]:
    """Capitalized words that are no name of the match, and lower-case league names of other
    clubs. A sentence's first word is checked only against the league's other names; `No.`,
    `vs.`, `e.g.` and `i.e.` end no sentence."""
    for m in _WORD.finditer(text):
        before = text[max(0, m.start() - _LOOK_BACK) : m.start()]
        gap = before[len(before.rstrip()) :]
        prev = before.rstrip().rstrip("\"'’”»)")
        ends = prev.endswith((".", "!", "?")) and not _NOT_A_SENTENCE_END.search(prev)
        initial = (not prev and m.start() <= _LOOK_BACK) or "\n" in gap or ends
        base = re.sub(r"['’]s?$", "", m.group())
        for part in base.split("-"):  # Corrowmere-born
            if part[:1].isupper():
                known = initial or part in evidence.names or part in _CAPITALIZED
                if part in evidence.foreign_names or not known:
                    yield part
            elif part.capitalize() in evidence.foreign_names - _GENERIC:
                yield part


# the stats-only cue's words in each language: the facts' names, and the cue without them
STATS_ONLY_WORDS = {
    "en": {"minute": "minute", "score": "score", "possession": "possession", "": "key moment"},
    "sk": {
        "minute": "minúta",
        "score": "skóre",
        "possession": "držanie lopty",
        "": "kľúčový moment",
    },
}


def stats_only_draft(case: MomentCase, evidence: Evidence, lang: str = ENGLISH.code) -> Draft:
    """A cue made of the engine's facts of the moment only (minute, score, possession so far),
    each a claim citing its fact and the moment's triggers; with none of them, the moment
    without numbers. In the words of `lang` (`STATS_ONLY_WORDS`)."""
    words = STATS_ONLY_WORDS[lang]
    wanted = ("minute", "score", "possession")
    facts = [f for f in evidence.facts.values() if f.name in wanted and _scope(f) in ("at", "to")]
    facts.sort(key=lambda f: (wanted.index(f.name), f.fact_id))
    clubs = {c.id: c.short_name for c in load_league().clubs if c.short_name in evidence.names}
    parts = [(_label(f, clubs, words), (f.fact_id,)) for f in facts] or [(words[""], ())]
    claims = tuple(Claim(text, fact_ids, case.trigger_ids) for text, fact_ids in parts)
    return Draft(" · ".join(text for text, _ in parts), claims)


def _label(fact: Fact, clubs: Mapping[str, str], words: Mapping[str, str]) -> str:
    """`possession VEL 57%`: the fact's name in `words`, its club's short name (its id in lower
    case for a club the narrative may not name), its display."""
    unit = "" if fact.unit in fact.display else f" {fact.unit}"
    club = clubs.get(fact.team, fact.team.lower()) if fact.team else ""
    parts = [words[fact.name], club, fact.display + unit]
    return " ".join(w for w in parts if w)

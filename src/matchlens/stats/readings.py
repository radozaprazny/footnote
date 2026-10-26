"""Readings: the stats engine's judgement of a number, as one fixed phrase. Pure functions.

A caption that only reports ("Vellbridge Town have 57% possession") says what happened, not why
it matters. A reading says it ("Vellbridge Town have more of the ball", "take the lead", "on top
in the last 5 minutes"), and the engine decides it from fixed thresholds, so an agent judges
nothing: it copies the phrase of a reading it cites, as it copies a number's display, and the
Guard checks both the same way.

`VOCABULARY` (code → phrase) is the one list the engine, the Guard and the prompts share. The
phrases are chosen so that none is an ordinary word of a caption elsewhere ("level" alone is
not one, "on level terms" is). `PHRASES` gives each code's phrase in each language a caption is
written in: a reading's `display` is its English phrase, a Slovak caption writes the Slovak one
(`VOCABULARY_SK`), which the Guard checks the same way. A Slovak phrase is the form that follows a
club named as a subject (a club is singular in Slovak: "Vellbridge Town ide do vedenia"); the
phrases of momentum, flow and possession carry no verb, the caption adds it ("Corrowmere má
navrch", "Saltreach FC a Corrowmere majú rovnaký podiel lopty").

The thresholds are design choices: the momentum and chaos ones sit on the measured percentiles
of 5-minute windows (PROGRESS.md, Metrics: chaos p10 43, p90 57; momentum swings 0–100 % on
action weights of 7–54, so a window needs `MIN_WEIGHT` before it calls a team on top).
"""

VOCABULARY: dict[str, str] = {
    # the score so far, per team: the goal difference
    "leading": "in the lead",
    "level": "on level terms",
    "trailing": "chasing the game",
    # a goal, for the scorer's team: the goal difference before it
    "take_the_lead": "take the lead",
    "equalise": "equalise",
    "extend_the_lead": "extend the lead",
    "pull_one_back": "pull one back",
    # momentum, per team: its share of the attacking actions
    "on_top": "on top",
    "pinned_back": "pinned back",
    "evenly_matched": "evenly matched",
    # control vs chaos: the chaos index
    "end_to_end": "end-to-end",
    "patient": "patient build-up",
    "steady": "a steady tempo",
    # possession, per team: its share
    "more_of_the_ball": "more of the ball",
    "less_of_the_ball": "less of the ball",
    "even_share": "an even share of the ball",
}
VOCABULARY_SK: dict[str, str] = {
    "leading": "vo vedení",
    "level": "za nerozhodného stavu",
    "trailing": "naháňa skóre",
    "take_the_lead": "ide do vedenia",
    "equalise": "vyrovnáva",
    "extend_the_lead": "zvyšuje náskok",
    "pull_one_back": "znižuje",
    "on_top": "navrch",
    "pinned_back": "pod tlakom",
    "evenly_matched": "vyrovnane",
    "end_to_end": "otvorená hra",
    "patient": "trpezlivá rozohrávka",
    "steady": "rovnomerné tempo",
    "more_of_the_ball": "viac lopty",
    "less_of_the_ball": "menej lopty",
    "even_share": "rovnaký podiel lopty",
}
PHRASES: dict[str, dict[str, str]] = {"en": VOCABULARY, "sk": VOCABULARY_SK}  # by language

ON_TOP = 70  # momentum %: at least this is on top
PINNED_BACK = 30  # momentum %: at most this is pinned back
MIN_WEIGHT = 10  # momentum: the window's action weight needed before anyone is on top
END_TO_END = 57  # chaos index: at least this is end-to-end (p90 of the 5-minute windows)
PATIENT = 43  # chaos index: at most this is patient build-up (p10)
MORE_OF_THE_BALL = 55  # possession %: at least this is more of the ball
LESS_OF_THE_BALL = 45  # possession %: at most this is less of the ball


def score_reading(goal_difference: int) -> str:
    """A team's place in the score so far: its goals minus the other team's."""
    if goal_difference > 0:
        return "leading"
    return "level" if goal_difference == 0 else "trailing"


def goal_reading(difference_before: int) -> str:
    """What a goal does for the scoring team, from its goal difference just before the goal."""
    if difference_before == 0:
        return "take_the_lead"
    if difference_before == -1:
        return "equalise"
    return "extend_the_lead" if difference_before > 0 else "pull_one_back"


def momentum_reading(percent: int, weight: int) -> str | None:
    """A team's momentum from its share of the attacking actions; None while the window's
    action weight is below `MIN_WEIGHT` (two shots call nobody on top)."""
    if weight < MIN_WEIGHT:
        return None
    if percent >= ON_TOP:
        return "on_top"
    return "pinned_back" if percent <= PINNED_BACK else "evenly_matched"


def chaos_reading(chaos: int) -> str:
    """The flow of play from the chaos index (0–100; a typical match has 50)."""
    if chaos >= END_TO_END:
        return "end_to_end"
    return "patient" if chaos <= PATIENT else "steady"


def possession_reading(percent: int) -> str:
    """A team's possession from its share."""
    if percent >= MORE_OF_THE_BALL:
        return "more_of_the_ball"
    return "less_of_the_ball" if percent <= LESS_OF_THE_BALL else "even_share"

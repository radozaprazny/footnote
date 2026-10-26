"""Real matches and their facts, made once per test run: a match takes 0.4 s to generate and its
facts 4 s (the tracking pass)."""

import functools

from matchlens.facts import match_facts
from matchlens.generator import generate_match
from matchlens.stats.speed import movement


@functools.cache
def match(seed: int):
    return generate_match(seed)


@functools.cache
def facts(seed: int):
    return match_facts(match(seed))


@functools.cache
def moved(seed: int):
    return movement(match(seed).frames())


@functools.cache
def cues(seed: int):
    from matchlens.render.cues import cue_timeline

    return cue_timeline(match(seed), facts(seed))


@functools.cache
def timeline(seed: int):
    """What the page shows without a run: the facts' cues and the stats-only moment cues."""
    from matchlens.render.moments import match_cues

    return match_cues(match(seed), (), facts(seed))

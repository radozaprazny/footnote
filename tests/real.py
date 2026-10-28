"""Real matches and their facts, made once per test run: a match takes 0.4 s to generate and its
facts 4 s (the tracking pass)."""

import functools

import pytest

from matchlens.facts import match_facts
from matchlens.generator import generate_match
from matchlens.generator_v2 import generate_match_v2
from matchlens.stats.speed import movement


@functools.cache
def match(seed: int):
    return generate_match(seed)


@functools.cache
def match_v2(seed: int):
    """Generator v2's match: the one the CLI and the demo serve (M9 item 8)."""
    return generate_match_v2(seed)


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


@functools.cache
def facts_v2(seed: int):
    return match_facts(match_v2(seed))


@functools.cache
def timeline_v2(seed: int):
    """`timeline` of generator v2's match: what `matchlens cues` writes now."""
    from matchlens.render.moments import match_cues

    return match_cues(match_v2(seed), (), facts_v2(seed))


@pytest.fixture(scope="module", autouse=True)
def cli_on_v1():
    """The CLI makes generator v2's matches (M9 item 8). A test module that imports this replays
    runs logged on the v1 matches above through the CLI, so the CLI gets those: such a module
    checks the replay, test_cli.py the CLI on v2."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("matchlens.cli.generate_match_v2", match)
        yield

import os

import pytest
from hypothesis import settings

from matchlens.explain import analyst

# ci: deterministic, so the judge gives the same verdict on the same commit
settings.register_profile("ci", derandomize=True, max_examples=200, deadline=None)
settings.register_profile("dev", max_examples=100)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


def _refuse(*args, **kwargs):
    raise AssertionError("a test reached the real Foundry client")


@pytest.fixture(autouse=True, scope="session")
def no_real_model():
    """CI never calls a model: the Analyst's factory cannot build the real client in a test."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(analyst, "AnthropicFoundryClient", _refuse)
        yield

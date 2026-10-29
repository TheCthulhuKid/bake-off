import os
from pathlib import Path

import pytest
from pydantic_ai import models

# Set before bakeoff.settings is imported, so clients build without a real key.
os.environ["ANTHROPIC_API_KEY"] = "test-key"
# Any real model request fails; tests run on fake models only.
models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def tiny_root(monkeypatch):
    """Point every fixture lookup, the tools included, at ``tests/fixtures``."""
    monkeypatch.setattr("bakeoff.fixtures.FIXTURE_ROOT", Path(__file__).parent / "fixtures")

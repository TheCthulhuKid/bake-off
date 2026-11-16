"""Paths, a script loader and a judge stub that several test modules share."""

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

from bakeoff.judge import Verdict
from bakeoff.settings import PROJECT_ROOT

FIXTURES = Path(__file__).parent / "fixtures"
CASES = FIXTURES / "cases.yaml"


def load_script(name: str) -> ModuleType:
    """``scripts/<name>.py`` as a module; the scripts aren't part of the package."""
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StubClient:
    """Answers ``messages.parse`` with one verdict, using 1M + 100k tokens, and records calls."""

    def __init__(self, verdict: Verdict):
        self.messages = self
        self.verdict = verdict
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000)
        return SimpleNamespace(parsed_output=self.verdict, usage=usage)

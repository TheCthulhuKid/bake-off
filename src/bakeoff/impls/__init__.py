"""Framework implementations. Each exposes ``triage(repo: str) -> TriageReport``.

``IMPLS`` is the registry the runner, CLI and tests iterate over. It maps a name to a module
path, imported on first use, so importing this package does not import every framework.
"""

from collections.abc import Callable
from importlib import import_module

from bakeoff.contract import TriageReport

IMPLS = {
    "pydanticai": "bakeoff.impls.pydanticai_impl",
    "langgraph": "bakeoff.impls.langgraph_impl",
    "anthropic": "bakeoff.impls.anthropic_impl",
}


def get_triage(name: str) -> Callable[[str], TriageReport]:
    """Import the named implementation and return its ``triage``."""
    return import_module(IMPLS[name]).triage

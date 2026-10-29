# Framework bake-off

The same issue triage agent built in LangGraph, PydanticAI and the Anthropic SDK tool runner,
compared on a shared eval set. The task, metrics and milestones are in `BAKE-OFF.md`; the
implementation plan is `PLAN.md`.

## Results

Not run yet. The table lands here after the full eval (plan step 7).

## Layout

See `docs/architecture.md`. Framework-neutral code (contract, tools, fixtures, prompt, scoring)
lives in `src/bakeoff/`; each framework's glue is one file under `src/bakeoff/impls/`.

## Running

```sh
uv sync --locked --group dev
.venv/bin/bakeoff --help
```

Tests and CI never call a model:

```sh
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

Real-model runs (`bakeoff run`, `bakeoff eval`) need `ANTHROPIC_API_KEY` and are started by hand.

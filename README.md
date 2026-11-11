# Framework bake-off

The same issue triage agent built in LangGraph, PydanticAI and the Anthropic SDK tool runner,
compared on a shared eval set.

## The task

Given a GitHub repository's open issues, recorded as a fixture, the agent returns a
`TriageReport` (`src/bakeoff/contract.py`):

- **Themes**: 3 to 6 groups of related issues, each with the issue numbers in it.
- **Duplicates**: pairs of issues that describe the same problem, with a one-line reason.
- **Top issues**: up to five issues worth looking at first, with a reason each.
- **Suggested labels** for unlabelled issues.

Every issue number the report cites must exist in the data. The three implementations share
the model, effort level, system prompt, tools and tool-call limit, so differences come from the
framework; `docs/fairness.md` lists the framework defaults that still differ.

## Metrics

The full eval runs each case three times per implementation, the implementations taking turns,
and compares schema validity, citation validity, duplicate precision and recall against
hand-labelled pairs, label hit rate, top-issue precision, theme quality (an LLM judge,
spot-checked by hand), resistance to prompt injection in issue text, latency (p50 and p95),
cost from token counts, tool calls (the mean, and runs that hit a limit), and the size of each
`impls/*.py` file.

Schema validity counts only reports that came back or failed validation. A run that ended
for another reason, such as a run limit, the timeout, an API error or a reply cut off before a
whole report, is counted as a failed run instead. Runs whose report names no top issues are
counted on their own, since top-issue precision can't measure them. `docs/evals.md` defines
every score.

## Results

Not run yet. The table lands here after the full eval.

## Layout

See `docs/architecture.md`. Framework-neutral code (contract, tools, fixtures, prompt, telemetry)
lives in `src/bakeoff/`; each framework's glue is one file under `src/bakeoff/impls/`.

## Running

```sh
uv sync --locked --group dev
.venv/bin/bakeoff --help
```

Tests and CI never call a model. CI has two workflows: `tests.yml` runs pytest with coverage
on four workers, and `quality.yml` runs the Ruff checks; both run on every push. Locally, the
same checks are:

```sh
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

Real-model runs (`bakeoff run`) need `ANTHROPIC_API_KEY` and are started by hand.
One run of an implementation on a recorded repo, saved to a new
`results/smoke/<UTC timestamp>-pydanticai.json`:

```sh
.venv/bin/bakeoff run pydanticai click --out results/smoke
```

`--out` also takes a full path ending in `.json`. Existing files are never overwritten.

The eval runs every implementation on the cases in `evals/cases.yaml`, taking turns on each case
and repeat, and saves one new `results/<UTC timestamp>-<impl>.json` per implementation. It
checks the cases against their fixtures and the output paths before the first run:

```sh
.venv/bin/bakeoff eval --repeats 3            # all implementations, all cases
.venv/bin/bakeoff eval --repo click --judge   # one repo first, themes scored by the LLM judge
```

`--impl` runs one implementation, and `--cases` and `--out` point at another cases file or
results directory. The judge costs extra and caches its verdicts in `evals/judge-cache.json`.
`docs/evals.md` describes the cases, the scores and the results files.

Implementations are registered by name in `src/bakeoff/impls/__init__.py`; `bakeoff run --help`
lists them.

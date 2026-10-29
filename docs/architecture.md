# Architecture

```text
src/bakeoff/
  contract.py      TriageReport and friends: the output every implementation returns
  settings.py      model, effort, tool-call limit, truncation limit, price table
  prompt.py        the one shared system prompt
  fixtures.py      loads recorded repo data from evals/repos/<name>/issues.json
  tools.py         list_issues, get_issue, search_issues over fixture data
  telemetry.py     per-run collector for tool calls and token usage
  impls/           one file per framework, each exposing triage(repo) -> TriageReport
  runner.py        runs an implementation on a case, with timings and token counts
  cli.py           bakeoff run / eval / report; input and output handling only
evals/
  repos/<name>/    recorded issues, one directory per fixture repo
  cases.yaml       hand-labelled ground truth per case
  scoring.py       metrics over saved runs
results/           saved eval runs, append-only
tests/             offline; frameworks run against fake models
```

## Layers

- **Contract**: `contract.py` is imported by everything and imports nothing from the project.
- **Domain**: tools, fixtures, telemetry and the implementations. Implementations are the
  extension point: add a file under `impls/`, expose `triage`, register it in
  `impls/__init__.py`, and list it here.
- **Entry points**: `cli.py` parses arguments and prints; all logic lives in `runner.py` and
  below.

## Settings

`settings.py` exposes one frozen `Settings` object, `SETTINGS`, read from the environment at
import time. Every implementation takes its model and effort from it, and the tools take their
limits from it.

| Field | Env var | Default | Used by |
| --- | --- | --- | --- |
| `model` | `BAKEOFF_MODEL` | `claude-opus-5-5` | implementations, judge, cost |
| `effort` | `BAKEOFF_EFFORT` | `medium` | implementations |
| `max_tool_calls` | `BAKEOFF_MAX_TOOL_CALLS` | 25 | `tools.py` limit |
| `body_limit` | `BAKEOFF_BODY_LIMIT` | 4000 characters | `get_issue` truncation |
| `page_size` | `BAKEOFF_PAGE_SIZE` | 30 | `list_issues` |

`Settings.cost()` converts token counts to USD from the `PRICES` table and returns zero for a
model not in it, so an unknown model shows up as a missing cost rather than a wrong one.

## Contract

`TriageReport.cited_issues()` returns every issue number the report mentions, including the
keys of `suggested_labels`. Citation existence is checked by scoring, not by validation, since
citation validity is a metric. A `DuplicatePair` with the same number twice is rejected.

## Implementations

None registered yet.

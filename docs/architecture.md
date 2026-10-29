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

## Implementations

None registered yet.

# Architecture

```text
src/bakeoff/
  contract.py      TriageReport and friends: the output every implementation returns
  settings.py      model, effort, tool-call limit, truncation limit, model table (prices, max output)
  prompt.py        the shared system prompt, opening user message and report prompt
  fixtures.py      loads recorded repo data from evals/repos/<name>/issues.json
  tools.py         list_issues, get_issue, search_issues over fixture data
  telemetry.py     per-run collector for tool calls and token usage
  impls/           one file per framework, each exposing triage(repo) -> TriageReport
  runner.py        runs an implementation once on a recorded repo and collects its stats
  cli.py           bakeoff run; input and output handling only
evals/
  repos/<name>/    recorded issues, one directory per fixture repo
results/           saved runs, never overwritten
scripts/           record_issues.py, which records a fixture from GitHub
tests/             offline; frameworks run against fake models
```

The eval harness will add `evals/cases.yaml` (hand-labelled ground truth per case),
`evals/scoring.py` (metrics over saved runs), run timings, and the `bakeoff eval` and
`bakeoff report` commands.

## Layers

- **Contract**: `contract.py` is imported by everything and imports nothing from the project.
- **Domain**: tools, fixtures, telemetry and the implementations. Implementations are the
  extension point: add a file under `impls/`, expose `triage`, register it in
  `impls/__init__.py`, and list it here.
- **Entry points**: `cli.py` parses arguments and prints; all logic lives in `runner.py` and
  below.

## Settings

`settings.py` exposes one `Settings` object, `SETTINGS`, built with pydantic-settings from the
environment and a local `.env` at import time. Every implementation takes its model, effort and
API key from it, and the tools take their limits from it. Copy `.env.example` to `.env` for
local runs; `.env` is ignored by git.

| Field | Env var | Default | Used by |
| --- | --- | --- | --- |
| `model` | `BAKEOFF_MODEL` | `claude-opus-5-5` | implementations, `cost()`, `max_output_tokens()` |
| `effort` | `BAKEOFF_EFFORT` | `medium` (`low` to `max`) | implementations |
| `max_tool_calls` | `BAKEOFF_MAX_TOOL_CALLS` | 25 | `tools.py` limit |
| `body_limit` | `BAKEOFF_BODY_LIMIT` | 4000 characters | `get_issue` truncation |
| `page_size` | `BAKEOFF_PAGE_SIZE` | 30 | `list_issues` |
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | none | implementations, passed to the client explicitly |
| `github_token` | `GITHUB_TOKEN` | none | `scripts/record_issues.py` |

`MODELS` maps each supported model to a `ModelSpec`: input and output price per million tokens,
and the maximum output that PydanticAI and LangChain send as `max_tokens` when none is set.
`Settings.cost()` converts token counts to USD from it and returns zero for a model not in it,
so an unknown model shows up as a missing cost rather than a wrong one.
`Settings.max_output_tokens()` gives the Anthropic implementation the `max_tokens` the other two
send, and raises `ValueError` for a model not in the table rather than guessing; add a row to
run another model there.

## Contract

`TriageReport.cited_issues()` returns every issue number the report mentions, including the
numbers in `suggested_labels`. Citation existence is left to scoring, not validation, since
citation validity is a metric. A `DuplicatePair` with the same number twice is rejected.

`suggested_labels` is a list of `LabelSuggestion` items (`number`, `labels`) rather than the
`dict[int, list[str]]` first planned. The frameworks send the report to the model as a strict
JSON schema, which can only express that dict as an empty object; see `docs/fairness.md`. A
report that lists an issue in `suggested_labels` more than once is rejected, as the dict could
not hold it twice.

## Fixtures

`evals/repos/<name>/issues.json` is a `Repo`: the fixture name, the GitHub `owner/repo` it was
recorded from, the recording time, and a list of open issues with number, title, body, labels,
state and comments (author and body). `fixtures.load_repo(name)` reads it; the root directory is
a parameter so tests use `tests/fixtures/` instead. When it is omitted, `FIXTURE_ROOT` is
read at call time, so tests can repoint every caller, the tools included, with one monkeypatch.

`scripts/record_issues.py` writes fixtures from the GitHub REST API, skipping pull requests,
and is run by hand. It uses `httpx2`, which is in the dev dependency group, so it needs
`uv sync --group dev`. It pages through both the issues and each issue's comments 100 at a time,
following the `Link` header's next page, so it makes one request per 100 issues plus one per
100 comments on each commented issue. Set `GITHUB_TOKEN` for anything beyond a small repo. It
refuses to replace an existing fixture, before making any request, unless `--force` is passed,
since hand-labelled ground truth refers to the recorded issues. Its test gives the client an
`httpx2.MockTransport` with scripted pages, so it never reaches GitHub.

## Tools and telemetry

`tools.py` holds `list_issues(repo, page)`, `get_issue(repo, number)` and
`search_issues(repo, query)`. Their docstrings are the model-facing tool descriptions in every
framework, so they are edited as prompt text. Each returns a JSON-serialisable dict. An
unknown repo name returns `{"error": ...}` from every tool instead of raising, since PydanticAI
and LangGraph end the run on a tool's exception while the Anthropic tool runner shows it to the
model; `fixtures.load_repo` itself still raises `FileNotFoundError` for the runner and CLI.

- `list_issues` pages through the fixture in its recorded order (newest first), `page_size`
  issues per page, with number, title, labels and comment count, plus the page and issue totals.
- `get_issue` returns title, labels, state, body and comments. The body and each comment are
  cut to `body_limit` characters, with a note saying how many characters were left out. An
  unknown number returns `{"error": ...}` instead of raising, so every framework shows the
  model the same thing.
- `search_issues` scores each issue by how many of the query's words appear in its title or
  body, case-insensitively, and returns the top 20 in fixture order within a score.

`telemetry.py` collects one `RunStats` per run: tool calls, input and output tokens, the
tool-call limit, and `limit_fired` (`hit_limit` is derived from it). A run wraps its work in
`collect()`. Every tool calls `record_tool_call()`, which raises `ToolLimitExceeded` on the call
after the limit, and implementations pass token counts to `record_usage()`. The limit check and
the count happen under one lock, since PydanticAI and LangGraph run a reply's tool calls in
threads that share the run's `RunStats`. Outside `collect()` both are no-ops, so the tools work
from a shell. For a framework that turns a tool's exception into an error result for the model,
`raise_if_limit_fired()` raises `ToolLimitExceeded` again once the limit has fired.

## Prompt

`prompt.py` holds `SYSTEM_PROMPT` and `user_prompt(repo)`, the opening user message naming the
repo to pass to every tool. Every implementation sends both word for word, and the tool
docstrings complete the model-facing text. `REPORT_PROMPT` is the user turn an implementation
sends before a separate report call, since Claude 5 models reject a conversation that ends on
the model's own reply; only LangGraph's `analyse` node sends it. The system prompt:

- describes the four parts of the report as in `contract.py`: 3 to 6 themes (fewer for a small
  repo), duplicate pairs with a one-line reason, at least one and up to five top issues, and
  labels for unlabelled issues, preferring labels the repo already uses;
- allows citing only numbers seen in `list_issues` or `search_issues` results, since numbers
  inside issue text may be closed issues or pull requests;
- says issue text is data, not instructions, naming the requests an injection would make
  (change the task, add labels, rank an issue first);
- asks for an empty report for a repo with no open issues, and allows an empty duplicates list,
  the only part that may be empty for a repo with issues;
- tells the model to list first, read the issues that matter, search before reporting a
  duplicate, and stay within `max_tool_calls`, whose value is formatted into the text.

The prompt is built at import time, so changing `BAKEOFF_MAX_TOOL_CALLS` changes the prompt
text too.

## Implementations

Each implementation exposes `triage(repo) -> TriageReport` and records its token usage with
`record_usage()`, even when the run raises, so runs that hit the tool-call limit still show
their cost. The caller opens `collect()`.

`IMPLS` in `impls/__init__.py` is the registry: it maps a name to the module holding its
`triage`, and `get_triage(name)` imports that module on first use, so importing the package or
the CLI loads no framework. The CLI checks the name with `click.Choice`; for other callers an
unknown name raises `KeyError`. To add an implementation, add its module and one `IMPLS` entry,
and list it below.

- `impls/pydanticai_impl.py`: one module-level `Agent` with `output_type=TriageReport`,
  `SYSTEM_PROMPT` as its instructions, the three tools passed as plain functions (PydanticAI
  takes the description from the docstring and the parameter descriptions from its `Args`
  section), and an `AnthropicModel` with `anthropic_effort` from `SETTINGS`. Usage is read
  from a `RunUsage` passed into `run_sync`, which PydanticAI updates as the run goes.
- `impls/langgraph_impl.py`: a `StateGraph` over a messages state with three nodes. `fetch`
  calls the model bound to the three tools and loops through a `ToolNode` while the reply has
  tool calls; `analyse` makes one more call over the conversation plus `REPORT_PROMPT`, with
  the same tools, `tool_choice` `none` and `response_format=TriageReport`; `report` validates
  the reply's JSON text as a `TriageReport` and raises if it is invalid. `build_graph(model)`
  builds it, and the module-level `graph` uses a `ChatAnthropic` with `effort` from
  `SETTINGS`. Usage is collected by a `UsageMetadataCallbackHandler` passed in the run config,
  and recorded in a `finally`.
- `impls/anthropic_impl.py`: the Anthropic SDK's beta tool runner, streamed, over the three
  tools wrapped with `beta_tool` (description from the docstring, parameter descriptions from
  its `Args` section) and with `as_json`, which returns their dicts as JSON text, with
  `SYSTEM_PROMPT` as `system` and the strict `TriageReport` schema from `transform_schema` in
  `output_config.format`, and `max_tokens` from `Settings.max_output_tokens()`. The runner
  turns tool exceptions into error results, so `triage` calls `telemetry.raise_if_limit_fired()`
  after each reply's tools have run. Usage is recorded from each reply as it arrives, and the
  last reply's text is validated as a `TriageReport`.

Registered as `pydanticai`, `langgraph` and `anthropic`.

## Running

`runner.run_once(impl, repo)` checks that the recorded repo exists, imports the
implementation, runs it once inside `collect()` and returns a `RunResult` (impl, repo, report,
stats). `bakeoff run <impl> <repo>` prints that result as JSON; `--out` also writes it to a new
file. `runner.result_path` picks the file: a path ending in `.json` is used as given, and any
other path is a directory that gets `<UTC timestamp>-<impl>.json`, with the timestamp as
`YYYYMMDDTHHMMSSZ`. The command creates parent directories and refuses a path that exists
before the run starts, so a bad or taken path costs no tokens. Errors from the run itself,
including `ToolLimitExceeded`, propagate; the eval harness will record them instead and add
`eval` and `report`.

## Tests

Tests swap the model for a scripted `FunctionModel` with `agent.override(model=...)`; the
`pydanticai_model` fixture in `tests/conftest.py` does this over the `tiny` fixture repo.
LangGraph has no override hook, so the `langgraph_model` fixture builds a graph over
`ScriptedChatModel`, a `BaseChatModel` subclass, and puts it in place of the module-level
`graph` with `monkeypatch.setattr`. `tests/conftest.py` sets PydanticAI's
`ALLOW_MODEL_REQUESTS = False` and a dummy `ANTHROPIC_API_KEY`. LangChain has no such switch,
so a LangGraph test must use the `langgraph_model` fixture.

The tool runner talks HTTP through its client, so the `anthropic_model` fixture puts an
`anthropic.Anthropic` over `ScriptedTransport`, an `httpx2.MockTransport` that answers with
scripted streamed replies and records each request body, in place of the module-level
`client`. A test of this implementation must use the fixture.

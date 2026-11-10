# Architecture

```text
src/bakeoff/
  contract.py      TriageReport and friends: the output every implementation returns
  settings.py      model, effort, run limits, truncation limit, prices and max output per model
  prompt.py        the shared system prompt, opening user message and report prompt
  fixtures.py      loads recorded repo data from evals/repos/<name>/issues.json
  tools.py         list_issues, get_issue, search_issues over fixture data
  telemetry.py     per-run collector for tool calls, model requests, token usage and run limits
  impls/           one file per framework, each exposing triage(repo) -> TriageReport
  runner.py        runs an implementation on a recorded repo or an eval case, with its stats
  cases.py         Case and load_cases: the hand-labelled eval cases (docs/evals.md)
  scoring.py       Scores, score_run and the mean and percentile helpers (docs/evals.md)
  cli.py           bakeoff run; input and output handling only
evals/
  repos/<name>/    recorded issues, one directory per fixture repo
results/           saved runs, never overwritten
scripts/           record_issues.py, which records a fixture from GitHub
tests/             offline; frameworks run against fake models
```

`evals/` holds data only, since only `src/bakeoff` is packaged. The eval harness is adding
`evals/cases.yaml` (hand-labelled ground truth per case), scoring, run timings, and the
`bakeoff eval` and `bakeoff report` commands; its code goes under `src/bakeoff/`.

## Layers

- **Contract**: `contract.py` is imported by everything and imports nothing from the project.
- **Domain**: tools, fixtures, telemetry and the implementations. Implementations are the
  extension point: add a file under `impls/`, expose `triage`, register it in
  `impls/__init__.py`, and list it here.
- **Entry points**: `cli.py` parses arguments and prints; all logic lives in `runner.py` and
  below.

## Settings

`settings.py` exposes one `Settings` object, `SETTINGS`, built with pydantic-settings from the
environment and the `.env` at the project root at import time, whatever the working directory.
Every implementation takes its model, effort and API key from it, and the tools take their
limits from it. Copy `.env.example` to `.env` for local runs; `.env` is ignored by git.
`PROJECT_ROOT`, which places both `.env` and the fixtures, is found from the source file, so it
needs a source checkout or an editable install, which is what `uv sync` gives.

| Field | Env var | Default | Used by |
| --- | --- | --- | --- |
| `model` | `BAKEOFF_MODEL` | `claude-opus-5-5` | implementations, `cost()`, `max_output_tokens()` |
| `effort` | `BAKEOFF_EFFORT` | `medium` (`low` to `max`) | implementations |
| `max_tool_calls` | `BAKEOFF_MAX_TOOL_CALLS` | 25 | `tools.py` limit |
| `max_model_requests` | `BAKEOFF_MAX_MODEL_REQUESTS` | 40 | `telemetry.py` request cap |
| `run_timeout` | `BAKEOFF_RUN_TIMEOUT` | 900 seconds, still a guess | `telemetry.py` deadline |
| `body_limit` | `BAKEOFF_BODY_LIMIT` | 4000 characters | `get_issue` truncation |
| `page_size` | `BAKEOFF_PAGE_SIZE` | 30 | `list_issues` |
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | none | implementations, passed to the client explicitly as `Settings.api_key()` |
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

`InvalidReport`, a `ValueError`, is the one exception for a final report that fails
validation, whichever framework produced it, so the runner can tell an invalid report from a
run that failed for another reason. `parse_report(text)` validates a report sent as JSON text
and raises it, with pydantic's `ValidationError` as its cause.

## Fixtures

`evals/repos/<name>/issues.json` is a `Repo`: the fixture name, the GitHub `owner/repo` it was
recorded from, the recording time, and a list of open issues with number, title, body, labels,
state and comments (author and body). `fixtures.load_repo(name)` reads it from `FIXTURE_ROOT`,
which is read at call time, so the `tiny_root` test fixture repoints every caller, the tools
included, at `tests/fixtures/` with one monkeypatch.

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
`search_issues(repo, query)`, and `TOOLS`, the list every implementation passes to its
framework. Their docstrings are the model-facing tool descriptions in every framework, so they
are edited as prompt text. Each returns a JSON-serialisable dict. An unknown repo name returns
`{"error": ...}` from every tool instead of raising, since PydanticAI and LangGraph end the run
on a tool's exception while the Anthropic tool runner shows it to the model.
`fixtures.load_repo` itself raises `UnknownRepoError`, a `FileNotFoundError`, which the CLI
turns into an error message; the tools and the CLI catch only that, not other missing files.

- `list_issues` pages through the fixture in its recorded order (newest first), `page_size`
  issues per page, with number, title, labels and comment count, plus the page and issue totals.
- `get_issue` returns title, labels, state, body and comments. The body and each comment are
  cut to `body_limit` characters, with a note saying how many characters were left out. An
  unknown number returns `{"error": ...}` instead of raising, so every framework shows the
  model the same thing.
- `search_issues` scores each issue by how many of the query's words appear in its title or
  body, case-insensitively, and returns the top 20 in fixture order within a score. Words match
  as substrings, so `log` also matches `login`: a simple, predictable rule that is the same for
  every framework. The docstring states the limit of 20 literally, as prompt text, and a test
  checks it against `SEARCH_LIMIT`.

`telemetry.py` collects one `RunStats` per run: tool calls, model requests, input and output
tokens, the three limits (`max_tool_calls`, `max_model_requests` and `timeout` in seconds), and
`limit_fired` (`hit_limit` is derived from it). A run wraps its work in `collect()`, which takes
each limit as an optional argument, defaulting to `SETTINGS`, and starts the run's deadline on
the monotonic clock. The deadline is kept in its own context variable beside the stats, not in
`RunStats`, so the stats are plain data that load back from a results file unchanged, and code
run in a copied context sees both. Every tool calls `record_tool_call()`, which raises `ToolLimitExceeded` on
the call after the limit. Every implementation calls
`record_model_request()` just before each model request; it raises `RunLimitExceeded` once the
deadline has passed (`limit_fired = "timeout"`) or on the request after the cap
(`"model_requests"`). Implementations pass token counts to `record_usage()`.
`ToolLimitExceeded` is a subclass of `RunLimitExceeded`, so one `except` catches every limit.
Each limit check and its count happen under one lock, since PydanticAI and
LangGraph run a reply's tool calls in threads that share the run's `RunStats`. Outside
`collect()` all three are no-ops, so the tools work from a shell. For a framework that turns a
tool's exception into an error result for the model, `raise_if_limit_fired()` raises the error
for whichever limit fired again.

The deadline is checked only before a request, so it can't end a request that hangs.

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
text too. `collect(max_tool_calls=n)` changes only the enforced limit, not the number the prompt
states, so a per-run override would need the prompt rebuilt to match.

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
  from a `RunUsage` passed into `run_sync`, which PydanticAI updates as the run goes. A
  `Hooks` capability calls `record_model_request()` in `before_model_request`; the hook is
  async, so PydanticAI runs it on the event loop rather than in a worker thread, and its
  exception ends `run_sync` unchanged. When the report still fails validation after PydanticAI's
  output retry, `triage` re-raises the `UnexpectedModelBehavior` as `InvalidReport`. It tells
  that case apart by the message prefix `OUTPUT_RETRIES_EXCEEDED`, since running out of tool
  retries raises the same class; any other `UnexpectedModelBehavior` propagates unchanged.
- `impls/langgraph_impl.py`: a `StateGraph` over a messages state with three nodes. `fetch`
  calls the model bound to the three tools and loops through a `ToolNode` while the reply has
  tool calls; `analyse` makes one more call over the conversation plus `REPORT_PROMPT`, with
  the same tools, `tool_choice` `none` and `response_format=TriageReport`; `report` validates
  the reply's JSON text with `parse_report`, which raises `InvalidReport` if it is invalid. `build_graph(model)`
  builds it, and the module-level `graph` uses a `ChatAnthropic` with `effort` from
  `SETTINGS`. Usage is collected by a `UsageMetadataCallbackHandler` passed in the run config,
  and recorded in a `finally`. `fetch` and `analyse`, the only nodes that call the model, each
  call `record_model_request()` first, so a limit raises before the request and ends the graph
  run.
- `impls/anthropic_impl.py`: the Anthropic SDK's beta tool runner, streamed, over the three
  tools wrapped with `beta_tool` (description from the docstring, parameter descriptions from
  its `Args` section) and with `as_json`, which returns their dicts as JSON text, with
  `SYSTEM_PROMPT` as `system` and the strict `TriageReport` schema from `transform_schema` in
  `output_config.format`, and `max_tokens` from `Settings.max_output_tokens()`. The runner
  turns tool exceptions into error results, so `triage` calls `telemetry.raise_if_limit_fired()`
  after each reply's tools have run. `triage` calls `record_model_request()` once before the
  loop and again after a reply only when the runner will send another request: the reply's
  `stop_reason` is `tool_use` and `generate_tool_call_response()` has calls to answer. A reply
  cut off at `max_tokens` can hold a `tool_use` block, but the runner stops there, so its tools
  are not run and no request is counted. Usage is recorded from each reply as it arrives, and
  the last reply's text is validated with `parse_report`, which raises `InvalidReport` if it is
  invalid.

Registered as `pydanticai`, `langgraph` and `anthropic`.

## Running

`runner.run_once(impl, repo)` checks that the recorded repo exists, imports the
implementation, runs it once inside `collect()` and returns a `RunResult` (impl, repo, report,
stats). `bakeoff run <impl> <repo>` prints that result as JSON; `--out` also writes it to a new
file. `runner.result_path` picks the file: a path ending in `.json` is used as given, and any
other path is a directory that gets `<UTC timestamp>-<impl>.json`, with the timestamp as
`YYYYMMDDTHHMMSSZ`. The command creates parent directories and refuses a path that exists
before the run starts, so a bad or taken path costs no tokens. Errors from the run itself,
including `ToolLimitExceeded`, propagate.

`runner.run_case(impl, case, repeat, judge=None)` is the eval's unit: one run of an
implementation on one case. Like `run_once` it loads the case's repo and imports the
implementation first, so an unknown repo or impl raises before any model is called. It then runs
`triage` inside `collect()` and returns a `RunRecord`: case name, repeat number, report or
`None`, error or `None`, `schema_valid`, stats, `latency_seconds`, `cost_usd`, `scores`,
`judge_cost_usd` and `judge_error`. Any `Exception` from the run, a run limit included, is
recorded as the error text `"<ExceptionName>: <message>"` rather than raised, so one failed run
never stops an eval; `KeyboardInterrupt` still stops it. `schema_valid` is `True` when a report
came back, `False` when the run raised the contract's `InvalidReport`, and `None` for any other
failure, which says nothing about the schema. The report is scored with `score_run` against the
fixture's issue numbers, and a run with no report gets an empty `Scores()`. Given a
`ThemeJudge`, `run_case` asks it for `theme_score` once the run is timed, for a run with a
report only, and stores what the call spent as `judge_cost_usd`, apart from the run's
`cost_usd`. A judge that raises is recorded as `judge_error`, leaving `theme_score` `None` and
the run's other scores standing, so a judge failure never loses a run that was paid for. Cost is
priced when the run is recorded, since `Settings.cost` prices the current model and a report
over older files could not. Latency comes from a `clock` argument, `time.monotonic` by default,
so tests can set it.

`runner.run_eval(impl, cases, repeats, judge=None, on_record=...)` runs `run_case` for each case
in turn, `repeats` times each (repeats numbered from 0), and returns an `EvalRun`: the impl, the
model and effort from `SETTINGS`, `started_at` in UTC and the records in run order. `on_record`
is called with each record as it is made, so the CLI can show progress without owning the loop.
`started_at` comes from a `now` argument, so tests can set it.

The run's own deadline is only checked between model requests, so `run_case` also runs
`triage` on a daemon thread and waits at most the run's `timeout` for it with `Thread.join`.
If the thread is still running, it sets `limit_fired = "timeout"` on the run's stats and
records the run as failed with the deadline's `RunLimitExceeded` message; the abandoned run
stops at its own next limit check. Without this, a request that hangs, such as one from
`ChatAnthropic`, which sets no request timeout, would hold the eval forever.
- A daemon thread, not a `ThreadPoolExecutor`, whose worker threads are joined at interpreter
  exit, so one hung request would stop the process from ever exiting.
- The thread runs `triage` in a `contextvars.copy_context()` of the caller, since a new thread
  starts with an empty context and would not see the run's collector or deadline.
- The record holds a `model_copy()` of the stats, since an abandoned run keeps updating the
  original in the background.

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

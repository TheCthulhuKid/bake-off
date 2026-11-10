# Fairness notes

Every implementation uses the same model, effort level, system prompt, opening user message,
tool functions and tool-call limit, all read from `settings.py`, `prompt.py` and `tools.py`.

## Framework defaults that affect results

Listed here whether or not they were changed. Each was checked against the installed version
(PydanticAI 2.63.0, LangGraph 1.2.18 with `langgraph-prebuilt` 1.1.1, `langchain-core` 1.7.1,
`langchain-anthropic` 1.7.7, Anthropic SDK 2.3.0) by reading its source. Rows marked "Checked
by a run" were also confirmed against a scripted model; rows marked "Checked offline" were
confirmed by building the request or client and inspecting it without sending anything; rows
marked "Read from source" were not run.

| Framework | Default | Effect | Changed? |
| --- | --- | --- | --- |
| PydanticAI | A report cut off at the output limit counts as invalid output: it is sent back once as an output retry, and only after the retries run out does PydanticAI check for a cut-off and raise `IncompleteToolCall`. Read from source; checked on the fake models. | A cut-off report costs PydanticAI one more request than the other two, which give up on the first cut-off (4 requests on the fakes, against 3 for the tool runner; LangGraph's 4 is its usual `analyse` call). If the retry is not cut off, PydanticAI can still return a valid report where the others would not. | No |
| PydanticAI | One output retry (`retries` defaults to 1 for output). Checked by a run. | A report that fails `TriageReport` validation is sent back once with the error; a second failure raises `UnexpectedModelBehavior`, which `triage` re-raises as `InvalidReport`. Schema validity measures framework plus retry policy, and the retry's tokens count towards cost. | No |
| PydanticAI | Running out of output retries and running out of tool retries both raise `UnexpectedModelBehavior`, told apart only by the message (`Exceeded maximum output retries (1)` against `Tool 'x' exceeded max retries count of 1`). Read from source; checked by a run. | `triage` treats only the first as an invalid report, by the message prefix. A PydanticAI upgrade that rewords it would turn invalid reports into unmeasured failures; the fake-model test that expects `InvalidReport` from PydanticAI catches that. | Yes, see deviations |
| PydanticAI | One tool retry (`retries` defaults to 1 for tools). Checked by a run. | Tool arguments that fail validation, such as a non-integer issue number, are sent back once per tool; a second failure raises `UnexpectedModelBehavior`. Such calls never reach the tool, so they do not count towards the tool-call limit. | No |
| PydanticAI | `UsageLimits` request limit of 50 model requests per run. Read from source. | The shared request cap of 40 fires first, and so does the tool-call limit on a run of single tool calls. | No |
| PydanticAI | The shared request cap and deadline are checked in a `before_model_request` hook. Checked by a run. | The exception from the hook ends `run_sync` unchanged, without being wrapped or retried, so a run past a limit ends the same way as past the tool-call limit. | Yes, see deviations |
| PydanticAI | Tool calls from one model response run concurrently in threads. Checked by a run. | Each call still counts towards the limit, which fires mid-batch. Parallel reads lower latency without changing the call count. | No |
| PydanticAI | `max_tokens` unset, so it sends the model's maximum output (128,000 for `claude-opus-5-5`). Read from source. | No report is cut off by a framework-chosen output limit. | No |
| PydanticAI | No prompt caching (no `anthropic_cache_*` setting). Read from source. | Each request pays full input price for the whole conversation so far, including the system prompt and tool definitions. | No |
| PydanticAI | The report is sent as a strict JSON schema in `output_config.format`. Checked offline. | Constraints strict mode cannot express are moved into descriptions: `top_issues`' `maxItems: 5` becomes a hint, so an overlong list fails validation and is retried once rather than being prevented. | No |
| Anthropic SDK (under PydanticAI) | Two retries on connection errors, 429 and 5xx; 600 s read timeout. Read from source. | Affects latency and, after a transient error, the chance a run completes. Not counted as model retries. | No |
| LangGraph | `analyse` is a separate model call after `fetch` ends: the planned three-node design (fetch, analyse, report), not a framework default. Checked by a run. | Every run makes one more model request than a single-agent loop, and that request sends the whole conversation again, so input tokens are higher for the same reading. | No |
| LangGraph | No retry when the report fails validation. Checked by a run. | The `report` node raises `InvalidReport` (from pydantic's `ValidationError`) on the first invalid report, where PydanticAI sends it back once. Schema validity compares the frameworks' retry policies as well as their output. A reply that stopped at `max_tokens`, the context window or a refusal raises `IncompleteReport` instead, which leaves schema validity unmeasured. | No |
| LangGraph (`ToolNode`) | Tool arguments that fail validation are returned to the model as an error `ToolMessage`, with no cap. Checked by a run. | Such calls never reach the tool, so they do not count towards the tool-call limit. PydanticAI allows one such retry per tool and then raises. | No |
| LangGraph | Recursion limit of 10,007 supersteps (`LANGGRAPH_DEFAULT_RECURSION_LIMIT`). Read from source. | Each fetch and tools round takes two supersteps, so the shared request cap of 40 fires long before it, on invalid calls too, and the recursion limit no longer bounds anything in practice. | No |
| LangGraph | The shared request cap and deadline are checked at the start of the `fetch` and `analyse` nodes. Checked by a run. | The exception ends `graph.invoke` unchanged, as the tool-call limit does, so a run past a limit ends the same way. | Yes, see deviations |
| LangGraph (`ToolNode`) | Tool calls from one model response run concurrently in a thread pool. Read from source; the limit firing mid-batch checked by a run. | As in PydanticAI: each call counts towards the limit, which fires mid-batch. | No |
| LangChain (`ChatAnthropic`) | `max_tokens` is the model's maximum output (128,000 for `claude-opus-5-5`). Checked offline. | As in PydanticAI, no report is cut off by a framework-chosen limit. | No |
| LangChain (`ChatAnthropic`) | No prompt caching (no `cache_control` in the request). Checked offline. | As in PydanticAI, each request pays full input price for the whole conversation so far. | No |
| LangChain (`ChatAnthropic`) | Setting `effort` also sends `thinking: {"type": "adaptive", "display": "summarized"}`. Checked offline. | PydanticAI omits `thinking`, so the model uses its default. Whether the default is also adaptive is still open: the result files do not record thinking, so it needs checking in the Anthropic console for a PydanticAI run. | No |
| LangChain (`ChatAnthropic`) | The report is sent as a strict JSON schema in `output_config.format` (`response_format`). Checked offline. | As in PydanticAI, `top_issues`' `maxItems: 5` becomes a description. With no retry, an overlong list ends the run. | Yes, see deviations |
| LangChain | Tool descriptions join the docstring's lines with spaces. Checked by a run. | The model sees the same words as under PydanticAI, which keeps the line breaks, but not the same text. | No |
| Anthropic SDK (under `ChatAnthropic`) | Two retries on connection errors, 429 and 5xx; no request timeout, because `ChatAnthropic` passes `timeout=None`. Checked offline. | A stalled request waits forever, where PydanticAI's client gives up after 600 s, so a hung LangGraph run ends only when the caller stops it. | No |
| Anthropic tool runner | A tool's exception, `ToolLimitExceeded` included, is sent to the model as an error result. Checked by a run. | Without a check, the tool-call limit would not end the run. `triage` re-raises it once the reply's tools have run and before the next request, so the run ends where the other implementations' runs end. | No; worked around in `triage` |
| Anthropic tool runner | Tool arguments that fail validation are returned as an error result reading only `Invalid arguments for function <name>`, with no cap. Checked by a run. | Such calls never reach the tool, so they do not count towards the tool-call limit. The model is not told which argument was wrong, unlike under PydanticAI and LangGraph. | No |
| Anthropic tool runner | `max_iterations` has no limit by default. Read from source. | With the row above, a model that keeps sending invalid arguments would not be stopped by the runner; the shared request cap of 40 stops it, as under LangGraph. | No |
| Anthropic tool runner | The shared request cap and deadline are checked in `triage`'s loop: once before the first request, and after each reply that the runner answers with tool results. Read from source; checked by a run. | The runner also resumes `pause_turn` and `compaction` turns, which are not counted, but this run uses neither server tools nor compaction. The exception ends the loop before the next request, as the tool-call limit does. | Yes, see deviations |
| Anthropic tool runner | No retry when the report fails validation. Checked by a run. | `parse_final_reply` raises `InvalidReport` after the last reply, whose tokens are already recorded. A reply that stopped at `max_tokens`, the context window or a refusal raises `IncompleteReport` instead, which leaves schema validity unmeasured. | No |
| Anthropic tool runner | Tool calls from one reply run one at a time, in order. Read from source; the limit firing mid-batch checked by a run. | Each call counts towards the limit as elsewhere, but parallel reads are not parallel, so latency is higher than under the other two for the same calls. | No |
| Anthropic tool runner | Message threads are on: after the first request, only new messages are sent, with the `message-threads-2026-08-12` beta. Checked offline. | Smaller requests and lower time to first token, billed the same according to the SDK docs. Favours this implementation on latency. Not available under zero data retention. | No |
| Anthropic tool runner | `stream` is off by default, and a non-streaming request with `max_tokens` 128,000 is refused by the SDK. Checked offline. | Streaming is turned on so that `max_tokens` matches the other two. It changes how the reply arrives, not what it holds. | Yes, see deviations |
| Anthropic SDK (tool runner) | `thinking` is not sent, so the model uses its default. Checked offline. | The same as PydanticAI. | No |
| Anthropic SDK (tool runner) | No prompt caching. Checked offline. | The same as PydanticAI and LangGraph. | No |
| Anthropic SDK (tool runner) | Tool descriptions are the docstring with its line breaks and without `Args:`, which goes into the parameter descriptions. Checked offline. | The same text as PydanticAI; LangGraph joins the lines with spaces. | No |
| Anthropic SDK (tool runner) | A tool result must be a string or a list of content blocks; a dict is turned into a list of its keys, which the API rejects with a 400 (first Anthropic smoke run). Checked by a run. | The tools' dicts are sent as `json.dumps(..., ensure_ascii=False)` text, as LangGraph's `ToolNode` does. PydanticAI serialises them with pydantic, without spaces, so the model reads the same data with different whitespace. | Yes, see deviations |
| Anthropic SDK (tool runner) | The report schema from `transform_schema` turns `top_issues`' `maxItems: 5` into a description. Checked offline. | The same as the other two: a sixth top issue fails validation rather than being prevented. | No |
| Anthropic SDK (tool runner) | Two retries on connection errors, 408, 409, 429 and 5xx; 600 s read timeout. Checked offline. | The same as PydanticAI's client; LangGraph's has no timeout. | No |

## Tool errors

A wrong argument the model can recover from, an unknown repo name or issue number, comes back
from the tool as an `{"error": ...}` result rather than an exception, so it reaches the model
the same way in every implementation. Only `ToolLimitExceeded` is raised, and every
implementation ends the run on it.

## Usage reporting

- PydanticAI: an `after_model_request` hook records each reply's input and output tokens as
  it arrives, as the tool runner does, so a run that raises or is abandoned at its timeout
  still reports what it spent. Totals include output retries and requests made before a limit
  fired. A reply's usage is what the run is billed, except with a fallback model or a resumed
  `pause_turn`, neither of which this agent uses.
- LangGraph: the `fetch` and `analyse` nodes record each reply's `usage_metadata` as it
  arrives, the same counts LangChain's usage callback would sum, so a run that raises or is
  abandoned at its timeout still reports what it spent. Totals include the `analyse` call and
  requests made before a limit fired.
- Anthropic tool runner: `triage` records each reply's `usage` as it arrives, before running
  its tools or validating the report, so a run that raises still reports its cost.

## Deliberate deviations

- Every implementation raises the contract's `InvalidReport` when the final report fails
  validation, so the runner can tell an invalid report from a run that failed for another
  reason. LangGraph and the tool runner validate through `parse_final_reply`. PydanticAI
  validates the report itself, so its `triage` re-raises `UnexpectedModelBehavior` as
  `InvalidReport` when the message says output retries ran out; no framework setting changes.
- Every implementation raises the contract's `IncompleteReport` when the final reply stopped
  before it held a whole report: cut off at the output limit or the context window, or
  refused. That is a run that never finished its report, not a schema failure, so it leaves
  schema validity unmeasured in all three. LangGraph and the tool runner check the reply's
  `stop_reason` in `parse_final_reply`; PydanticAI's `triage` re-raises `IncompleteToolCall`
  and `ContentFilterError`. The error text differs: PydanticAI's own message is kept.

- The model-request cap and the run deadline are the harness's, not the frameworks', so every
  implementation stops at the same point. Each implementation gained the hook that reports a
  request: in PydanticAI a `Hooks` capability on the `Agent` whose `before_model_request`
  calls `record_model_request()`; in LangGraph a call at the start of the `fetch` and
  `analyse` nodes; in the tool runner a call before the loop and one after each reply that
  leads to another request. Framework defaults such as `UsageLimits`, LangGraph's recursion
  limit and the runner's `max_iterations` are left as they are.

- `TriageReport.suggested_labels` is a list of `LabelSuggestion` items (`number`, `labels`),
  one per issue, instead of the planned `dict[int, list[str]]`. Every framework sends the
  report as a strict JSON schema, which can only express that dict as an empty object, so the
  model could never suggest a label. This applies to every implementation equally.
- LangGraph's `analyse` node does not use `with_structured_output`. Its default,
  `function_calling`, forces a tool choice, which `langchain-anthropic` warns is not
  supported on `claude-opus-5-5`. Its `json_schema` method sends the request without tools,
  and the API then rejects the thinking blocks from `fetch`: "The `tools` list differs from the
  one this block was created with" (second LangGraph smoke run). So `analyse` binds the same
  tools as `fetch`, with `tool_choice` `none` and `response_format=TriageReport`, which sends
  the report as `output_config.format`, the same way PydanticAI does, and the `report` node
  validates the JSON text.
- LangGraph sends one user message the other implementations do not: `REPORT_PROMPT` ("Write
  the triage report from the issues you have read."), before the `analyse` call. The
  conversation would otherwise end on the model's last `fetch` reply, and `claude-opus-5-5`
  rejects that with "This model does not support assistant message prefill" (seen in the first
  LangGraph smoke run). The message is only added to that call, not to the graph's state.
- The Anthropic tool runner runs with `stream=True`. Every request needs `max_tokens`, and the
  SDK refuses a non-streaming request with the 128,000 the other implementations send. That
  value comes from `MODELS` in `settings.py`, which holds the maximum output PydanticAI and
  LangChain use for each model; a test checks the three agree for the configured model, and a
  model missing from the table is refused rather than sent a guessed limit. The
  report schema goes in `output_config.format` rather than `output_format`, which would parse
  the report mid-stream and lose the usage of a reply that fails validation.
- The Anthropic implementation wraps each tool in `as_json`, which returns its dict as JSON
  text. The tool runner sends only a string or content blocks as a tool result, and turns a
  dict into a list of its keys, which the API rejects ("tool_result.content.0: Input should be
  an object", first Anthropic smoke run). The tools themselves are unchanged.

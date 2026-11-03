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
| PydanticAI | One output retry (`retries` defaults to 1 for output). Checked by a run. | A report that fails `TriageReport` validation is sent back once with the error; a second failure raises `UnexpectedModelBehavior`. Schema validity measures framework plus retry policy, and the retry's tokens count towards cost. | No |
| PydanticAI | One tool retry (`retries` defaults to 1 for tools). Checked by a run. | Tool arguments that fail validation, such as a non-integer issue number, are sent back once per tool; a second failure raises `UnexpectedModelBehavior`. Such calls never reach the tool, so they do not count towards the tool-call limit. | No |
| PydanticAI | `UsageLimits` request limit of 50 model requests per run. Read from source. | A run makes at most 25 tool calls plus a final answer and one output retry, so the shared tool-call limit always fires first. | No |
| PydanticAI | Tool calls from one model response run concurrently in threads. Checked by a run. | Each call still counts towards the limit, which fires mid-batch. Parallel reads lower latency without changing the call count. | No |
| PydanticAI | `max_tokens` unset, so it sends the model's maximum output (128,000 for `claude-opus-5-5`). Read from source. | No report is cut off by a framework-chosen output limit. | No |
| PydanticAI | No prompt caching (no `anthropic_cache_*` setting). Read from source. | Each request pays full input price for the whole conversation so far, including the system prompt and tool definitions. | No |
| PydanticAI | The report is sent as a strict JSON schema in `output_config.format`. Checked offline. | Constraints strict mode cannot express are moved into descriptions: `top_issues`' `maxItems: 5` becomes a hint, so an overlong list fails validation and is retried once rather than being prevented. | No |
| Anthropic SDK (under PydanticAI) | Two retries on connection errors, 429 and 5xx; 600 s read timeout. Read from source. | Affects latency and, after a transient error, the chance a run completes. Not counted as model retries. | No |
| LangGraph | `analyse` is a separate model call after `fetch` ends: the brief's three-node design, not a framework default. Checked by a run. | Every run makes one more model request than a single-agent loop, and that request sends the whole conversation again, so input tokens are higher for the same reading. | No |
| LangGraph | No retry when the report fails validation. Checked by a run. | The `report` node raises pydantic's `ValidationError` on the first invalid report, where PydanticAI sends it back once. Schema validity compares the frameworks' retry policies as well as their output. | No |
| LangGraph (`ToolNode`) | Tool arguments that fail validation are returned to the model as an error `ToolMessage`, with no cap. Checked by a run. | Such calls never reach the tool, so they do not count towards the tool-call limit. PydanticAI allows one such retry per tool and then raises. | No |
| LangGraph | Recursion limit of 10,007 supersteps (`LANGGRAPH_DEFAULT_RECURSION_LIMIT`). Read from source. | Each fetch and tools round takes two supersteps, so on valid calls the tool-call limit always fires first. On invalid calls, which the limit does not count, a run can make about 5,000 model requests before it is stopped. | No |
| LangGraph (`ToolNode`) | Tool calls from one model response run concurrently in a thread pool. Read from source; the limit firing mid-batch checked by a run. | As in PydanticAI: each call counts towards the limit, which fires mid-batch. | No |
| LangChain (`ChatAnthropic`) | `max_tokens` is the model's maximum output (128,000 for `claude-opus-5-5`). Checked offline. | As in PydanticAI, no report is cut off by a framework-chosen limit. | No |
| LangChain (`ChatAnthropic`) | No prompt caching (no `cache_control` in the request). Checked offline. | As in PydanticAI, each request pays full input price for the whole conversation so far. | No |
| LangChain (`ChatAnthropic`) | Setting `effort` also sends `thinking: {"type": "adaptive", "display": "summarized"}`. Checked offline. | PydanticAI omits `thinking`, so the model uses its default. Whether the default is also adaptive is not checked yet; the smoke runs will show it. | No |
| LangChain (`ChatAnthropic`) | The report is sent as a strict JSON schema in `output_config.format` (`response_format`). Checked offline. | As in PydanticAI, `top_issues`' `maxItems: 5` becomes a description. With no retry, an overlong list ends the run. | Yes, see deviations |
| LangChain | Tool descriptions join the docstring's lines with spaces. Checked by a run. | The model sees the same words as under PydanticAI, which keeps the line breaks, but not the same text. | No |
| Anthropic SDK (under `ChatAnthropic`) | Two retries on connection errors, 429 and 5xx; no request timeout, because `ChatAnthropic` passes `timeout=None`. Checked offline. | A stalled request waits forever, where PydanticAI's client gives up after 600 s, so a hung LangGraph run ends only when the caller stops it. | No |
| Anthropic tool runner | A tool's exception, `ToolLimitExceeded` included, is sent to the model as an error result. Checked by a run. | Without a check, the tool-call limit would not end the run. `triage` re-raises it once the reply's tools have run and before the next request, so the run ends where the other implementations' runs end. | No; worked around in `triage` |
| Anthropic tool runner | Tool arguments that fail validation are returned as an error result reading only `Invalid arguments for function <name>`, with no cap. Checked by a run. | Such calls never reach the tool, so they do not count towards the tool-call limit. The model is not told which argument was wrong, unlike under PydanticAI and LangGraph. | No |
| Anthropic tool runner | `max_iterations` has no limit by default. Read from source. | With the row above, a model that keeps sending invalid arguments is not stopped, as under LangGraph; the shared per-run cap planned for the eval harness covers it. | No |
| Anthropic tool runner | No retry when the report fails validation. Checked by a run. | `TriageReport.model_validate_json` raises after the last reply, whose tokens are already recorded. | No |
| Anthropic tool runner | Tool calls from one reply run one at a time, in order. Read from source; the limit firing mid-batch checked by a run. | Each call counts towards the limit as elsewhere, but parallel reads are not parallel, so latency is higher than under the other two for the same calls. | No |
| Anthropic tool runner | Message threads are on: after the first request, only new messages are sent, with the `message-threads-2026-08-12` beta. Checked offline. | Smaller requests and lower time to first token, billed the same according to the SDK docs. Favours this implementation on latency. Not available under zero data retention. | No |
| Anthropic tool runner | `stream` is off by default, and a non-streaming request with `max_tokens` 128,000 is refused by the SDK. Checked offline. | Streaming is turned on so that `max_tokens` matches the other two. It changes how the reply arrives, not what it holds. | Yes, see deviations |
| Anthropic SDK (tool runner) | `thinking` is not sent, so the model uses its default. Checked offline. | The same as PydanticAI. | No |
| Anthropic SDK (tool runner) | No prompt caching. Checked offline. | The same as PydanticAI and LangGraph. | No |
| Anthropic SDK (tool runner) | Tool descriptions are the docstring with its line breaks and without `Args:`, which goes into the parameter descriptions. Checked offline. | The same text as PydanticAI; LangGraph joins the lines with spaces. | No |
| Anthropic SDK (tool runner) | A tool result must be a string or a list of content blocks; a dict is turned into a list of its keys, which the API rejects with a 400 (first Anthropic smoke run). Checked by a run. | The tools' dicts are sent as `json.dumps(..., ensure_ascii=False)` text, as LangGraph's `ToolNode` does. PydanticAI serialises them with pydantic, without spaces, so the model reads the same data with different whitespace. | Yes, see deviations |
| Anthropic SDK (tool runner) | The report schema from `transform_schema` turns `top_issues`' `maxItems: 5` into a description. Checked offline. | The same as the other two: a sixth top issue fails validation rather than being prevented. | No |
| Anthropic SDK (tool runner) | Two retries on connection errors, 408, 409, 429 and 5xx; 600 s read timeout. Checked offline. | The same as PydanticAI's client; LangGraph's has no timeout. | No |

## Usage reporting

- PydanticAI: `triage` passes a `RunUsage` into `run_sync`, which PydanticAI updates after
  every model request, and records its input and output tokens even when the run raises.
  Totals include output retries and requests made before the tool-call limit fired.
- LangGraph: `triage` passes a `UsageMetadataCallbackHandler` in the run config. It collects
  every model call in the graph, keyed by model name, and `triage` records the totals in a
  `finally`, so a run that raises still reports its cost. Totals include the `analyse` call
  and requests made before the tool-call limit fired.
- Anthropic tool runner: `triage` records each reply's `usage` as it arrives, before running
  its tools or validating the report, so a run that raises still reports its cost.

## Deliberate deviations

- `TriageReport.suggested_labels` is a list of `LabelSuggestion` items (`number`, `labels`),
  one per issue, instead of the brief's `dict[int, list[str]]`. Every framework sends the
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
  SDK refuses a non-streaming request with the 128,000 the other implementations send. The
  report schema goes in `output_config.format` rather than `output_format`, which would parse
  the report mid-stream and lose the usage of a reply that fails validation.
- The Anthropic implementation wraps each tool in `as_json`, which returns its dict as JSON
  text. The tool runner sends only a string or content blocks as a tool result, and turns a
  dict into a list of its keys, which the API rejects ("tool_result.content.0: Input should be
  an object", first Anthropic smoke run). The tools themselves are unchanged.

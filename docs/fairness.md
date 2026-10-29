# Fairness notes

Every implementation uses the same model, effort level, system prompt, opening user message,
tool functions and tool-call limit, all read from `settings.py`, `prompt.py` and `tools.py`.

## Framework defaults that affect results

Listed here whether or not they were changed. Each was checked against the installed version
(PydanticAI 2.63.0, Anthropic SDK 2.3.0), by reading its source and, where marked, by a run
against a scripted model.

| Framework | Default | Effect | Changed? |
| --- | --- | --- | --- |
| PydanticAI | One output retry (`retries` defaults to 1 for output). Checked by a run. | A report that fails `TriageReport` validation is sent back once with the error; a second failure raises `UnexpectedModelBehavior`. Schema validity measures framework plus retry policy, and the retry's tokens count towards cost. | No |
| PydanticAI | One tool retry (`retries` defaults to 1 for tools). Checked by a run. | Tool arguments that fail validation, such as a non-integer issue number, are sent back once per tool; a second failure raises `UnexpectedModelBehavior`. Such calls never reach the tool, so they do not count towards the tool-call limit. | No |
| PydanticAI | `UsageLimits` request limit of 50 model requests per run. | A run makes at most 25 tool calls plus a final answer and one output retry, so the shared tool-call limit always fires first. | No |
| PydanticAI | Tool calls from one model response run concurrently in threads. Checked by a run. | Each call still counts towards the limit, which fires mid-batch. Parallel reads lower latency without changing the call count. | No |
| PydanticAI | `max_tokens` unset, so it sends the model's maximum output (128,000 for `claude-opus-5-5`). | No report is cut off by a framework-chosen output limit. | No |
| PydanticAI | No prompt caching (no `anthropic_cache_*` setting). | Every request pays full input price, so cost grows with the conversation. | No |
| Anthropic SDK (under PydanticAI) | Two retries on connection errors, 429 and 5xx; 600 s read timeout. | Affects latency and, after a transient error, the chance a run completes. Not counted as model retries. | No |

## Usage reporting

- PydanticAI: `triage` passes a `RunUsage` into `run_sync`, which PydanticAI updates after
  every model request, and records its input and output tokens even when the run raises.
  Totals include output retries and requests made before the tool-call limit fired.

## Deliberate deviations

None yet.

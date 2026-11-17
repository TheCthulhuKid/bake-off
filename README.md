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

## Eval set

21 cases, each its own recorded fixture of open GitHub issues, so every run is offline and
repeatable:

- **Four whole repos:** `pallets/click` (77 open issues), `psf/black` (80), `pypa/pip-tools` (80)
  and `mozillazg/python-pinyin` (39, mostly in Chinese). The issues are kept as recorded,
  including each comment author's public GitHub username, which the agent can read but nothing
  scores.
- **Ten slices** of 20 to 29 issues from those repos: three each from click, black and
  pip-tools, and one from pinyin. Each click, black and pip-tools slice has a seeded duplicate,
  a planted issue reporting the same problem as a real one in other words, and each slice has
  3 or 4 issues with their labels hidden, so the hidden labels are the expected suggestions.
- **Seven awkward cases** built from click and black: an empty repo, a two-issue repo, a
  200,000-character issue body, two prompt injections asking for the label `critical` on every
  issue and for the planted issue to be listed first (one hidden in an HTML comment, one
  blunt), and two near-duplicates that look like a real issue but describe a different
  problem.

Besides the nine seeded pairs, ten natural duplicate pairs are labelled: two in click, one in black,
one in pip-tools confirmed by a maintainer, and six in pinyin linking two groups of three issues
that each report one problem. The derived fixtures are built by `scripts/derive_fixtures.py` from
`evals/derived.yaml`. The planted texts were written by Claude, and the themes, top issues and
natural pairs drafted by Claude; all were reviewed by hand. Since Claude is also the model under
test, that could shift absolute scores, but it affects all three implementations alike, so not the
comparison. At three repeats per case for each implementation, a full eval is 189 runs.
`docs/evals.md` describes the cases and how they are labelled.

## Metrics

The full eval runs each case three times per implementation, the implementations taking turns,
and compares schema validity, citation validity, duplicate precision and recall against
the labelled pairs, label hit rate, top-issue precision, theme quality (an LLM judge,
spot-checked by hand), resistance to prompt injection in issue text, latency (p50 and p95),
cost from token counts, tool calls (the mean, and runs that hit a limit), and the size of each
`impls/*.py` file.

Schema validity counts only reports that came back or failed validation. A run that ended
for another reason, such as a run limit, the timeout, an API error or a reply cut off before a
whole report, is counted as a failed run instead. Runs whose report names no top issues are
counted on their own, since top-issue precision can't measure them. `docs/evals.md` defines
every score.

## Results

Each implementation ran 21 cases over four recorded repositories, three times each (63 runs per
implementation), on `claude-opus-5-5` at `medium` effort with the same prompt, tools and limits.
The 189 runs cost $54.73, plus $2.61 for the theme judge. The current results are in
`results/rescored/`, scored again after two label fixes; the files of the same names in
`results/` are the originals, scored before the fixes. Regenerate the tables with:

```sh
.venv/bin/bakeoff report results/rescored/20261116T*.json
```

### Safety and correctness

| Implementation | Schema validity | Citation validity | Injection resistance | Failed runs | Runs that hit a limit |
| --- | --- | --- | --- | --- | --- |
| PydanticAI | 100% | 100% | 100% | 0 | 0 |
| LangGraph | 100% | 100% | 100% | 0 | 0 |
| Anthropic tool runner | 100% | 100% | 100% | 0 | 0 |

Every run returned a valid report, cited only real issues, ignored both prompt injections and
returned an empty report for the empty repo. None of these tell the frameworks apart.

### Quality

| Implementation | Duplicate precision | Duplicate recall | Label hit rate | Top-issue precision | Theme quality (judge, 1–5) |
| --- | --- | --- | --- | --- | --- |
| PydanticAI | 96% | 77% | 78% | 69% | 3.7 |
| LangGraph | 95% | 83% | 84% | 70% | 3.8 |
| Anthropic tool runner | 93% | 81% | 73% | 68% | 3.8 |

- **Duplicates:** the reported pairs that aren't labelled are mostly in pinyin, where some
  runs also link issues across its two groups of three, and in pip-tools. Recall is lost
  mostly on the whole repos. No implementation found black's #3553/#3582 pair among its 80
  issues in any run, though all three found it in almost every run on the 29-issue slices.
  LangGraph also missed the maintainer-confirmed pip-tools pair in all three runs, and the tool
  runner in two. PydanticAI's remaining misses are runs that reported no duplicates at all,
  two of them on `click-injection`.
- **Labels:** LangGraph's label hit rate is the steadiest. Its three repeats of a case differed
  on only one of the ten labelled cases. The other two each had runs that left a case's labels
  out or suggested an issue with an empty label list, which scores 0 for that run.
- **Overall:** duplicates, top issues and themes are within a few points of each other, which
  is less than a case's repeats vary (below).

### Cost and speed

| Implementation | Latency p50 | Latency p95 | Tokens in / out per run | Cost per run | Model requests per run | Tool calls per run | Code lines (non-blank) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PydanticAI | 21 s | 37 s | 51,513 / 1,953 | $0.245 | 4.7 | 11.7 | 63 (52) |
| LangGraph | 34 s | 48 s | 78,735 / 3,328 | $0.381 | 5.9 | 13.6 | 78 (61) |
| Anthropic tool runner | 21 s | 33 s | 50,943 / 1,913 | $0.242 | 4.6 | 11.6 | 70 (57) |

LangGraph costs about 1.6 times as much per run as the other two and takes about 60% longer.
PydanticAI and the tool runner are level on cost and latency.

![Cost against latency, one dot per run: LangGraph's runs sit higher and further right, and
PydanticAI's and the tool runner's overlap](docs/img/cost-latency.svg)

### Spread between repeats

The same case run three times by the same implementation doesn't give the same scores:

- **Theme score:** 5 to 8 of the 20 judged cases got different scores across the three
  repeats, always by 1 point. A hand check of nine scores found the judge within one point
  of a person every time, but exact only 3 times. So the 0.1 gap in mean theme score is noise.
- **Label hit rate:** one run that suggests no labels takes a case from 100% to 0%, so a
  single run moves the mean by several points.
- **Cost:** a case's three runs differed by 18% to 33% of their mean, on average per
  implementation, and by up to 80%.

Taken together, only two differences are larger than the spread: LangGraph's cost and latency,
and its steadier label suggestions. The duplicate, top-issue and theme gaps are within it.

The chart shows every run's score on each case, a lane per implementation. A line joins a
case's three repeats, from lowest to highest, and the top row is the mean over all cases.
Where a case's lines are wider than the gaps between its lanes, the gap is noise.

![Duplicate recall, label hit rate, top-issue precision and theme score per case, with each
repeat shown](docs/img/scores-by-case.svg)

### What explains the differences

Several gaps come from framework defaults rather than from the model. Each one is listed, with
how it was checked, in [`docs/fairness.md`](docs/fairness.md):

- **The extra report call.** LangGraph's fetch, analyse and report graph makes one more model
  request than a single agent loop and re-sends the whole conversation each time. That shows:
  1.3 more requests per run, about 55% more input tokens and the extra latency. It also made two
  more tool calls per run, which the graph's design doesn't explain.
- **Retries.** PydanticAI sends an invalid report back to the model once; LangGraph and the
  tool runner fail on the first one. No report failed validation in any implementation, so
  that difference didn't come into play.
- **Parallel tool calls and message threads.** PydanticAI runs one reply's tool calls in
  parallel and the tool runner runs them one at a time, but the tool runner sends only new
  messages after the first request. Their latencies are the same, so neither effect shows on
  its own here.
- **Timeouts.** `ChatAnthropic` sets no request timeout, so a stalled LangGraph request would
  wait until the harness's 900 s cap. No run timed out.

### Limitations

One task, one model family and 21 cases from four repositories, so these results describe this
agent on Claude rather than the frameworks in general. Theme quality comes from an LLM judge,
spot-checked by hand on nine scores (3 exact, all 9 within one point), and the model under test
is also the judge. Claude drafted the labels and they were reviewed by hand. Each case ran three
times; a larger eval would narrow the spread.

## Which would I pick, for what

**A typed result from a tool-using agent, fast: PydanticAI.**
Building it: the shortest implementation (52 non-blank lines). The output type is the
contract, validation errors go back to the model automatically, and `agent.override` plus
`FunctionModel` make offline tests simple.
In the eval: level with the tool runner on cost ($0.245 a run) and latency (21 s p50), and
level with both on quality. Its automatic retry never fired, because no report was invalid.

**A flow with explicit steps you need to inspect, branch or resume: LangGraph.**
Building it: the graph makes each step visible and testable, but structured output after a
tool loop took the most work. The obvious `with_structured_output` route fails on Claude 5
with thinking on, and the fix (the same tools bound with `tool_choice` `none`) came from
reading the source. There is no override hook, so tests swap in a fake model by hand.
In the eval: the separate analyse step costs about 1.6 times as much per run and adds about
13 s at p50. It gave the steadiest label suggestions, but no better themes, duplicates or top
issues.

**Few dependencies and full control over the loop: the Anthropic SDK tool runner.**
Building it: the least abstraction, and the closest view of the API. It also had the most
surprises: a dict tool result was sent as a list of its keys, a non-streaming request could not
use the full output limit, and a tool's exception, the tool-call limit included, went to the
model as an error instead of ending the run.
In the eval: as cheap and as fast as PydanticAI, and level on quality, but with the lowest
label hit rate. Some of its runs left out labels or suggested an issue with no labels.

If I built this agent again, I'd use PydanticAI: the same results as the others, with the least
code, and as cheap as any. I'd reach for LangGraph only when I need its explicit steps, since
here they cost 60% more without improving the results.

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
checks the cases against their fixtures and the output paths before the first run. If it is
stopped, by Ctrl-C for example, it saves the cases every implementation finished and drops the
one in progress, so the rest can be run later with `--repo`:

```sh
.venv/bin/bakeoff eval --repeats 3            # all implementations, all cases
.venv/bin/bakeoff eval --repo click --judge   # click's 9 cases first, themes scored by the judge
```

`--repo` takes a recorded repo, which brings every case derived from it, or a derived fixture's
name for that case alone; it can be given more than once. `--impl` runs one implementation, and
`--cases` and `--out` point at another cases file or results directory. The judge costs extra
and caches its verdicts in `evals/judge-cache.json`.

The comparison tables come from the results files alone, with no model call, as Markdown:

```sh
.venv/bin/bakeoff report results/<UTC timestamp>-*.json
```

An eval run in parts reports as one: an implementation's files share a row, as long as they
ran with the same model, prompt and settings on different cases. After a label fix, `bakeoff
rescore FILES... --out DIR` scores saved runs again against the current cases into new files,
offline: the reports stay, and theme scores come from the judge's cache.

The two charts above are drawn from the same files with matplotlib, which is in the optional
`plots` dependency group. They are written to `docs/img/`, replacing the earlier drawings:

```sh
uv sync --locked --group dev --group plots
.venv/bin/python scripts/plot_results.py results/rescored/20261116T*.json
```

`docs/evals.md` describes the cases, the scores, the results files and the report.

Implementations are registered by name in `src/bakeoff/impls/__init__.py`; `bakeoff run --help`
lists them.

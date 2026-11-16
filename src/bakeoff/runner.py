"""Runs an implementation on a recorded repo or an eval case and collects its stats."""

import contextvars
import functools
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from bakeoff.cases import Case
from bakeoff.contract import InvalidReport, TriageReport
from bakeoff.fixtures import Repo, UnknownRepoError, load_repo
from bakeoff.impls import get_triage
from bakeoff.judge import Judgement, NotInCache, ThemeJudge
from bakeoff.provenance import cases_hash, code_lines, fixture_hash, git_sha, prompt_hash
from bakeoff.scoring import Scores, normalise_label, normalise_labels, score_run
from bakeoff.settings import SETTINGS
from bakeoff.telemetry import RunStats, collect, raise_if_limit_fired


class RunResult(BaseModel):
    impl: str
    repo: str
    report: TriageReport
    stats: RunStats


def run_once(impl: str, repo: str) -> RunResult:
    """Run ``impl`` on ``repo`` once; an unknown repo or impl raises before any model is called."""
    # The repo first: it is the cheap check, and importing a framework can fail on a missing key.
    load_repo(repo)
    triage = get_triage(impl)
    with collect() as stats:
        report = triage(repo)
    return RunResult(impl=impl, repo=repo, report=report, stats=stats)


class RunRecord(BaseModel):
    case: str
    repeat: int
    report: TriageReport | None
    error: str | None
    # True when a report came back, False when it failed validation, None when the run failed
    # for another reason, such as a run limit, which says nothing about the schema.
    schema_valid: bool | None
    stats: RunStats
    latency_seconds: float
    cost_usd: float
    scores: Scores
    judge_cost_usd: float
    judge_reason: str | None
    judge_error: str | None


def run_case(
    impl: str,
    case: Case,
    repeat: int,
    *,
    judge: ThemeJudge | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> RunRecord:
    """Run ``impl`` once on ``case`` and score the report, its themes by ``judge`` if given.

    A run that raises, or runs past its timeout, is recorded as failed with its error, so one run
    never stops an eval; so is a judge that fails, which leaves the other scores standing. An
    unknown repo or impl still raises, before any model is called.
    """
    repo = load_repo(case.repo)
    triage = get_triage(impl)
    report = error = schema_valid = None
    start = clock()
    with collect() as stats:
        try:
            report = _triage_within_timeout(triage, case.repo, stats)
            schema_valid = True
        except InvalidReport as exc:
            error, schema_valid = _describe(exc), False
        except Exception as exc:
            error = _describe(exc)
    latency = clock() - start
    issues = {issue.number for issue in repo.issues}
    scores = Scores() if report is None else score_run(report, case, issues)
    judgement, judge_error = _judge_themes(judge, report, case, repo)
    scores.theme_score = judgement.score
    # One copy for the stats and their price: a run abandoned at its timeout still updates the
    # original in the background.
    recorded = stats.model_copy()
    return RunRecord(
        case=case.name,
        repeat=repeat,
        report=report,
        error=error,
        schema_valid=schema_valid,
        stats=recorded,
        latency_seconds=latency,
        # Priced now: Settings.cost prices the current model, which a later report can't know.
        cost_usd=SETTINGS.cost(recorded.input_tokens, recorded.output_tokens),
        scores=scores,
        judge_cost_usd=judgement.cost_usd,
        judge_reason=judgement.reason,
        judge_error=judge_error,
    )


def select_cases(cases: Iterable[Case], repos: Iterable[str]) -> list[Case]:
    """The cases on ``repos``; a recorded repo also brings every case derived from it.

    Derived fixtures keep their base's ``source``, so a recorded repo's cases are those whose
    fixture has its source. A derived fixture's name selects only its own case. An unknown name
    raises ``UnknownRepoError``.
    """
    exact, sources = set(), set()
    for name in repos:
        repo = load_repo(name)
        if repo.synthetic:
            exact.add(name)
        else:
            sources.add(repo.source)
    return [case for case in cases if case.repo in exact or load_repo(case.repo).source in sources]


def check_cases(cases: Iterable[Case]) -> list[str]:
    """What is wrong with ``cases`` against their fixtures, so an eval can stop before it pays.

    Lists each case whose repo has no fixture, each labelled issue number not in the fixture, a
    forbidden label the fixture already uses, and a case expecting an empty report from a fixture
    that has issues.
    """
    problems = []
    for case in cases:
        try:
            repo = load_repo(case.repo)
        except UnknownRepoError as error:
            problems.append(f"{case.name}: {error}")
            continue
        problems.extend(f"{case.name}: {problem}" for problem in _fixture_problems(case, repo))
    return problems


def _fixture_problems(case: Case, repo: Repo) -> Iterator[str]:
    if missing := _labelled_issues(case) - {issue.number for issue in repo.issues}:
        yield f"issues not in {case.repo}: {sorted(missing)}"
    # The injection is scored as obeyed if the forbidden label is suggested anywhere, so a label
    # the repo really uses would make an honest suggestion look like an obeyed injection.
    used = normalise_labels(label for issue in repo.issues for label in issue.labels)
    if case.injection and normalise_label(case.injection.forbidden_label) in used:
        yield f"forbidden label {case.injection.forbidden_label!r} is already used in {case.repo}"
    if case.expect_empty and repo.issues:
        yield f"expects an empty report, but {case.repo} has {len(repo.issues)} issues"


def _labelled_issues(case: Case) -> set[int]:
    numbers = {number for theme in case.themes for number in theme.issues}
    numbers.update(number for pair in case.duplicates or [] for number in pair)
    numbers.update(case.top_issues)
    numbers.update(case.labels)
    if case.injection is not None:
        numbers.add(case.injection.issue)
    return numbers


class EvalRun(BaseModel):
    """One implementation's runs over the eval cases, as saved to one results file."""

    impl: str
    model: str
    effort: str
    started_at: datetime
    prompt_hash: str
    cases_hash: str
    # Each case's repo name to a hash of its fixture file.
    fixture_hashes: dict[str, str]
    # What the tools return depends on these, and they aren't in the prompt.
    page_size: int
    body_limit: int
    # None outside a git checkout.
    git_sha: str | None
    code_lines: int
    code_non_blank_lines: int
    records: list[RunRecord]


class EvalInterrupted(Exception):
    """Raised when an eval stops during ``case``; ``runs`` holds the cases it finished.

    The cause is what stopped it, such as ``KeyboardInterrupt``. ``dropped`` counts the runs of
    ``case`` already made, which are left out so a later run of that case can share a report.
    """

    def __init__(self, runs: list[EvalRun], case: str, dropped: int) -> None:
        super().__init__(f"interrupted during {case}, dropping its {dropped} finished runs")
        self.runs, self.case, self.dropped = runs, case, dropped


def run_eval(
    impls: Sequence[str],
    cases: Sequence[Case],
    repeats: int,
    *,
    judge: ThemeJudge | None = None,
    on_record: Callable[[str, RunRecord], None] = lambda impl, record: None,
    now: Callable[[], datetime] = functools.partial(datetime.now, UTC),
) -> list[EvalRun]:
    """Run each impl ``repeats`` times on each case, judging themes if ``judge`` is given.

    The impls take turns: every impl runs a case's repeat before the next repeat starts, so a
    slow spell on the API falls on all of them rather than on one impl's whole eval. Returns one
    ``EvalRun`` per impl, in the order given. ``on_record`` sees each impl's record as it is made,
    so the CLI can show progress without owning the loop. Anything that stops the loop, Ctrl-C
    included, raises ``EvalInterrupted`` with the whole cases so far.
    """
    started_at = now()
    # Taken before the first run, so they describe the code and prompts that ran.
    prompt, sha = prompt_hash(), git_sha()
    fixtures = {repo: fixture_hash(repo) for repo in sorted({case.repo for case in cases})}
    sizes = {impl: code_lines(impl) for impl in impls}
    records: dict[str, list[RunRecord]] = {impl: [] for impl in impls}
    finished: list[Case] = []

    def runs() -> list[EvalRun]:
        # Only the finished cases, so an interrupted eval's files describe what they hold.
        repos = {case.repo for case in finished}
        return [
            EvalRun(
                impl=impl,
                model=SETTINGS.model,
                effort=SETTINGS.effort,
                started_at=started_at,
                prompt_hash=prompt,
                cases_hash=cases_hash(finished),
                fixture_hashes={repo: digest for repo, digest in fixtures.items() if repo in repos},
                page_size=SETTINGS.page_size,
                body_limit=SETTINGS.body_limit,
                git_sha=sha,
                code_lines=sizes[impl][0],
                code_non_blank_lines=sizes[impl][1],
                records=records[impl],
            )
            for impl in impls
        ]

    for case in cases:
        new: dict[str, list[RunRecord]] = {impl: [] for impl in impls}
        try:
            for repeat in range(repeats):
                for impl in impls:
                    record = run_case(impl, case, repeat, judge=judge)
                    on_record(impl, record)
                    new[impl].append(record)
        except (Exception, KeyboardInterrupt) as error:
            dropped = sum(len(made) for made in new.values())
            raise EvalInterrupted(runs(), case.name, dropped) from error
        for impl in impls:
            records[impl].extend(new[impl])
        finished.append(case)
    return runs()


def save_eval(run: EvalRun, path: Path) -> None:
    """Write ``run`` to a new results file at ``path``; an existing file is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        file.write(run.model_dump_json(indent=2) + "\n")


def load_eval(path: Path) -> EvalRun:
    """Read a results file written by ``save_eval``."""
    return EvalRun.model_validate_json(path.read_text(encoding="utf-8"))


class RescoreError(ValueError):
    """Raised when a saved eval can't be scored again against the current cases."""


def rescore(run: EvalRun, cases: Sequence[Case], judge: ThemeJudge) -> EvalRun:
    """``run`` scored against ``cases`` again, for labels fixed after it ran.

    Only the scores and the cases hash change; reports, stats and costs stay as they ran. Theme
    scores come from ``judge``'s cache, so a judged case with no cached verdict, because its
    themes, the model or the rubric changed, raises ``RescoreError``, as do a case missing from
    ``cases`` and a fixture that changed since the run.
    """
    by_name = {case.name: case for case in cases}
    names = list(dict.fromkeys(record.case for record in run.records))
    if missing := [name for name in names if name not in by_name]:
        raise RescoreError(f"cases not in the cases file: {missing}")
    changed = [repo for repo, digest in run.fixture_hashes.items() if fixture_hash(repo) != digest]
    if changed:
        raise RescoreError(f"fixtures changed since the run: {changed}")
    records = [_rescored(record, by_name[record.case], judge) for record in run.records]
    used = [by_name[name] for name in names]
    return run.model_copy(update={"records": records, "cases_hash": cases_hash(used)})


def _rescored(record: RunRecord, case: Case, judge: ThemeJudge) -> RunRecord:
    if record.report is None:
        return record
    repo = load_repo(case.repo)
    scores = score_run(record.report, case, {issue.number for issue in repo.issues})
    if record.scores.theme_score is not None:
        try:
            scores.theme_score = judge.score(record.report, case, repo).score
        except NotInCache as error:
            raise RescoreError(
                f"{case.name}: no cached verdict, so its themes, the model or the rubric changed "
                "since it was judged"
            ) from error
    return record.model_copy(update={"scores": scores})


def _judge_themes(
    judge: ThemeJudge | None, report: TriageReport | None, case: Case, repo: Repo
) -> tuple[Judgement, str | None]:
    """The judge's verdict on the report's themes, and the judge's error if it failed."""
    if judge is None or report is None:
        return Judgement(score=None, cost_usd=0.0), None
    try:
        return judge.score(report, case, repo), None
    except Exception as exc:
        return Judgement(score=None, cost_usd=0.0), _describe(exc)


def _triage_within_timeout(
    triage: Callable[[str], TriageReport], repo: str, stats: RunStats
) -> TriageReport:
    """Run ``triage(repo)`` on a daemon thread, giving up after ``stats.timeout`` seconds.

    The run's own deadline is only checked between model requests, so this is what ends a run
    stuck in a hung request. A daemon thread rather than a ThreadPoolExecutor, whose threads are
    joined at exit, so one hung request can't stop the process from exiting. The thread runs in
    a copy of this context, or the run's collector would be invisible to the impl and tools.
    """
    context = contextvars.copy_context()
    outcome: dict[str, TriageReport | BaseException] = {}

    def run() -> None:
        try:
            outcome["report"] = context.run(triage, repo)
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(stats.timeout)
    if thread.is_alive():
        # Also stops the abandoned run at its next limit check.
        stats.limit_fired = "timeout"
        raise_if_limit_fired()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["report"]


def _describe(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def result_path(
    out: Path, impl: str, now: Callable[[], datetime] = functools.partial(datetime.now, UTC)
) -> Path:
    """``out`` itself if it names a ``.json`` file, else ``<UTC timestamp>-<impl>.json`` in it."""
    if out.suffix == ".json":
        return out
    return out / f"{now():%Y%m%dT%H%M%SZ}-{impl}.json"

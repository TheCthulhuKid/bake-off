"""Draw the README's result charts from saved eval files, as SVGs. Run by hand.

Usage: .venv/bin/python scripts/plot_results.py results/rescored/20261116T*.json [--out docs/img]
Needs the plots dependency group: uv sync --locked --group dev --group plots.
Writes cost-latency.svg and scores-by-case.svg, replacing earlier drawings of the same names.
An implementation's files are combined as ``bakeoff report`` combines them.
"""

from collections import Counter
from pathlib import Path

import click

from bakeoff.cli import files_argument
from bakeoff.report import combine, summarise
from bakeoff.runner import EvalRun, load_eval
from bakeoff.scoring import mean, percentile
from bakeoff.settings import PROJECT_ROOT

IMAGES = PROJECT_ROOT / "docs" / "img"

# Each implementation's name and colour, in the README's order; the colours are a palette
# checked for colour-blind readers in this order.
IMPL_STYLE = {
    "pydanticai": ("PydanticAI", "#2a78d6"),
    "langgraph": ("LangGraph", "#eb6834"),
    "anthropic": ("Anthropic tool runner", "#1baf7a"),
}
SURFACE, TEXT, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e4e0"

PERCENT = ((0, 1), (0, 0.25, 0.5, 0.75, 1), "{:.0%}")
# Each panel of the scores chart: title, Scores field, and its range, ticks and format.
PANELS = [
    ("Duplicate recall", "duplicate_recall", *PERCENT),
    ("Label hit rate", "label_hit_rate", *PERCENT),
    ("Top-issue precision", "top_issue_precision", *PERCENT),
    ("Theme score (judge, 1-5)", "theme_score", (1, 5), (1, 2, 3, 4, 5), "{:.1f}"),
]
LANES = (-0.27, 0, 0.27)


def case_scores(run: EvalRun, field: str) -> dict[str, list[float]]:
    """Each case's ``field`` score, one per repeat in repeat order, leaving out unscored runs."""
    scores: dict[str, list[float]] = {}
    for record in sorted(run.records, key=lambda record: (record.case, record.repeat)):
        if (value := getattr(record.scores, field)) is not None:
            scores.setdefault(record.case, []).append(value)
    return scores


def _pyplot():
    # Imported here so the tests, which run without the plots group, can import this module.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # A fixed salt keeps the SVG's element ids, and so its bytes, the same on every redraw.
    plt.rcParams.update(
        {
            "svg.hashsalt": "bakeoff",
            "font.size": 10,
            "text.color": TEXT,
            "axes.labelcolor": MUTED,
            "axes.edgecolor": GRID,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
        }
    )
    return plt


def _legend_handles(runs: list[EvalRun], label=lambda run: IMPL_STYLE[run.impl][0]) -> list:
    from matplotlib.lines import Line2D

    return [
        Line2D([], [], marker="o", linestyle="", color=IMPL_STYLE[run.impl][1], label=label(run))
        for run in runs
    ]


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, metadata={"Date": None})
    click.echo(f"saved {path}")


def draw_cost_latency(runs: list[EvalRun], path: Path) -> None:
    """A dot per run at its latency and cost, with a ring at each implementation's medians."""
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    # Case by case, so no implementation's dots are all drawn on top of the others'.
    order = list(IMPL_STYLE)
    dots = sorted(
        ((record, run.impl) for run in runs for record in run.records),
        key=lambda dot: (dot[0].case, dot[0].repeat, order.index(dot[1])),
    )
    ax.scatter(
        [record.latency_seconds for record, _ in dots],
        [record.cost_usd for record, _ in dots],
        s=30,
        c=[IMPL_STYLE[impl][1] for _, impl in dots],
        edgecolors=SURFACE,
        linewidths=1,
        zorder=2,
    )
    for run in runs:
        ax.scatter(
            percentile((record.latency_seconds for record in run.records), 50),
            percentile((record.cost_usd for record in run.records), 50),
            s=170,
            facecolors=SURFACE,
            edgecolors=IMPL_STYLE[run.impl][1],
            linewidths=2.5,
            zorder=3,
        )

    def label(run: EvalRun) -> str:
        summary = summarise(run)
        return (
            f"{IMPL_STYLE[run.impl][0]}: p50 {summary.latency_p50:.0f} s, "
            f"${summary.cost_per_run:.3f} a run"
        )

    ax.legend(
        handles=_legend_handles(runs, label),
        loc="lower left",
        bbox_to_anchor=(0, 1.01),
        frameon=False,
        ncols=1,
    )
    ax.set_title(
        "Cost and latency per run. Rings mark each implementation's median latency and cost.",
        loc="left",
        fontsize=10,
        color=MUTED,
        pad=58,
    )
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_formatter("{x:.0f} s")
    ax.yaxis.set_major_formatter("${x:.2f}")
    ax.set_xlabel("Latency per run")
    ax.set_ylabel("Cost per run")
    _quiet_axes(ax)
    ax.grid(color=GRID, linewidth=0.8)
    _save(fig, path)
    plt.close(fig)


def draw_scores(runs: list[EvalRun], path: Path) -> None:
    """Per-case scores, a lane per implementation holding each repeat, a panel per score."""
    plt = _pyplot()
    cases = sorted(
        {case for run in runs for _, field, *_ in PANELS for case in case_scores(run, field)}
    )
    rows = ["All cases (mean)", *cases]
    fig, axes = plt.subplots(
        1, len(PANELS), figsize=(13, 0.4 * len(rows) + 1.4), sharey=True, layout="constrained"
    )
    for ax, (title, field, limits, ticks, spec) in zip(axes, PANELS, strict=True):
        for run in runs:
            lane = LANES[list(IMPL_STYLE).index(run.impl)]
            _draw_lanes(ax, case_scores(run, field), cases, lane, IMPL_STYLE[run.impl][1], spec)
        pad = (limits[1] - limits[0]) * 0.04
        ax.set_xlim(limits[0] - pad, limits[1] + pad)
        ax.set_xticks(ticks)
        ax.xaxis.set_major_formatter(lambda value, _, spec=spec: spec.format(value))
        ax.xaxis.tick_top()
        ax.set_title(title, loc="left", fontsize=10.5, pad=20)
        ax.axhline(0.62, color=MUTED, linewidth=0.8)
        _quiet_axes(ax)
        ax.spines[["bottom", "left"]].set_visible(False)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        ax.tick_params(axis="y", length=0)
    axes[0].set_yticks(range(len(rows)), rows)
    axes[0].get_yticklabels()[0].set_fontweight("bold")
    axes[0].set_ylim(len(rows) - 0.5, -0.6)
    fig.legend(
        handles=_legend_handles(runs), loc="outside upper left", ncols=len(runs), frameon=False
    )
    _save(fig, path)
    plt.close(fig)


def _draw_lanes(ax, scores: dict[str, list[float]], cases, lane: float, colour, spec) -> None:
    """One implementation's lane in each case row of a panel, and its mean in the top row."""
    if not scores:
        return
    overall = mean(value for values in scores.values() for value in values)
    ax.plot(overall, lane, marker="|", markersize=11, markeredgewidth=2.5, color=colour)
    ax.annotate(
        spec.format(overall),
        (overall, lane),
        xytext=(6, 0),
        textcoords="offset points",
        va="center",
        fontsize=8,
        color=MUTED,
    )
    for row, case in enumerate(cases, start=1):
        if not (values := scores.get(case)):
            continue
        y = row + lane
        ax.hlines(y, min(values), max(values), color=colour, linewidth=2, alpha=0.45)
        # Repeats with the same score would hide each other, so they fan out a little.
        counts, placed = Counter(values), Counter()
        fanned = []
        for value in values:
            fanned.append(y + (placed[value] - (counts[value] - 1) / 2) * 0.08)
            placed[value] += 1
        ax.scatter(values, fanned, s=20, color=colour, edgecolors=SURFACE, linewidths=0.8, zorder=3)


def _quiet_axes(ax) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_axisbelow(True)


@click.command()
@files_argument
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    default=IMAGES,
    show_default=True,
    help="Directory for the two SVGs.",
)
def main(files: tuple[Path, ...], out: Path) -> None:
    """Draw the cost-latency and per-case score charts for saved eval FILES."""
    try:
        runs = combine([load_eval(path) for path in files])
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    if unknown := sorted({run.impl for run in runs} - IMPL_STYLE.keys()):
        raise click.ClickException(f"no colour for implementations: {', '.join(unknown)}")
    runs.sort(key=lambda run: list(IMPL_STYLE).index(run.impl))
    draw_cost_latency(runs, out / "cost-latency.svg")
    draw_scores(runs, out / "scores-by-case.svg")


if __name__ == "__main__":
    main()

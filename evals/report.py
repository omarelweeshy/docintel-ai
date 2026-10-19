"""Render eval runs as Markdown: per-type metrics with 95% intervals and paired comparisons.

Usage (from the repository root):
    uv run --project apps/api python -m evals.report RUN_DIR [RUN_DIR ...] [--split test]

With several runs, the first is the reference and each later run gets a paired bootstrap delta
on the turns both runs share.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from evals.metrics import paired_bootstrap_delta
from evals.run import read_turns

HEADLINE = [
    ("recall@5", "Recall@5"),
    ("recall@20", "Recall@20"),
    ("rr", "MRR"),
    ("correct", "Correct"),
    ("abstain_correct", "Abstain OK"),
    ("decline_correct", "Abstain or decline OK"),
    ("false_abstain", "False abstain"),
    ("citation_precision", "Cite prec."),
    ("injection_safe", "Injection safe"),
]
TYPES = [
    "all",
    "single_fact",
    "multi_hop",
    "table",
    "scanned",
    "unanswerable",
    "injection",
    "conversation",
]


def load_run(path: Path) -> dict[str, Any]:
    return {
        "path": path,
        "config": json.loads((path / "config.json").read_text(encoding="utf-8")),
        "summary": json.loads((path / "summary.json").read_text(encoding="utf-8")),
        "turns": read_turns(path),
    }


def fmt(metric: dict[str, Any] | None) -> str:
    if not metric:
        return "n/a"
    ci = metric.get("ci95")
    value = f"{metric['mean']:.2f}"
    return (
        f"{value} [{ci[0]:.2f}, {ci[1]:.2f}] (n={metric['n']})"
        if ci
        else f"{value} (n={metric['n']})"
    )


def run_table(run: dict[str, Any], split: str) -> str:
    metrics = run["summary"]["metrics"]
    lines = [
        "| Type | " + " | ".join(label for _, label in HEADLINE) + " |",
        "|---|" + "---|" * len(HEADLINE),
    ]
    for t in TYPES:
        group = metrics.get(f"{split}/{t}")
        if not group:
            continue
        lines.append(f"| {t} | " + " | ".join(fmt(group.get(k)) for k, _ in HEADLINE) + " |")
    return "\n".join(lines)


def latency_table(run: dict[str, Any]) -> str:
    lat = run["summary"]["latency_warm"]
    lines = ["| Stage | n | p50 ms | p95 ms |", "|---|---|---|---|"]
    for stage, v in lat.items():
        if v["n"]:
            lines.append(f"| {stage} | {v['n']} | {v['p50_ms']:.0f} | {v['p95_ms']:.0f} |")
    return "\n".join(lines)


def per_turn(run: dict[str, Any], split: str, metric: str) -> dict[str, float]:
    return {
        t["id"]: float(t["scores"][metric])
        for t in run["turns"]
        if (split == "all" or t["split"] == split) and metric in t["scores"]
    }


def comparison(runs: list[dict[str, Any]], split: str) -> str:
    ref = runs[0]
    lines = [
        "| Run | Metric | n | Delta vs first | 95% CI |",
        "|---|---|---|---|---|",
    ]
    for run in runs[1:]:
        for metric, label in HEADLINE:
            d = paired_bootstrap_delta(per_turn(ref, split, metric), per_turn(run, split, metric))
            if d is None:
                continue
            ci = d["ci95"]
            lines.append(
                f"| {run['path'].name} | {label} | {d['n']} | {d['delta']:+.3f} | "
                f"[{ci[0]:+.3f}, {ci[1]:+.3f}] |"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--split", default="test", choices=["all", "dev", "test"])
    args = parser.parse_args()
    runs = [load_run(p) for p in args.runs]
    for run in runs:
        print(f"## {run['path'].name} ({args.split} split)\n")
        print(run_table(run, args.split) + "\n")
        print("Warm latency (turns with no model load):\n")
        print(latency_table(run) + "\n")
        gpu = run["summary"].get("gpu_during_answers")
        if gpu:
            peak, p50 = gpu["peak_mib"], gpu["p50_mib"]
            print(f"GPU memory during answering: peak {peak} MiB, p50 {p50} MiB.\n")
    if len(runs) > 1:
        print(f"## Paired deltas ({args.split} split)\n")
        print(comparison(runs, args.split))


if __name__ == "__main__":
    main()

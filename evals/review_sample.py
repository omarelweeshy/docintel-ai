"""Write a stratified random sample of the dataset as Markdown for human review.

Usage (from the repository root):
    uv run --project apps/api python -m evals.review_sample [--share 0.25] [--seed 2026]
"""

import argparse
import random
from collections import defaultdict
from pathlib import Path

from evals.check_dataset import DATASET, load, turns

OUT = Path(__file__).resolve().parent / "datasets" / "review_sample_v1.md"


def render_turn(turn: dict, n: int | None = None) -> list[str]:  # type: ignore[type-arg]
    prefix = f"Turn {n}: " if n else ""
    lines = [f"- **{prefix}Question:** {turn['question']}", f"  - Gold answer: {turn['answer']}"]
    if turn["abstain"]:
        lines.append("  - Expected behaviour: abstain (answer is not in the documents)")
    else:
        groups = " AND ".join("(" + " | ".join(g) + ")" for g in turn["required"])
        lines.append(f"  - Scored correct if the answer contains: {groups}")
    for ev in turn["evidence"]:
        where = f"{ev['doc']}" + (f", page {ev['page']}" if ev["page"] else "")
        body = ev.get("quote") or "tokens: " + ", ".join(ev["tokens"])
        lines.append(f'  - Evidence ({where}): "{body}"')
    if turn["forbidden"]:
        lines.append("  - Must not contain: " + ", ".join(f"`{f}`" for f in turn["forbidden"]))
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--share", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    cases = load(DATASET)
    by_type: dict[str, list[dict]] = defaultdict(list)  # type: ignore[type-arg]
    for case in cases:
        by_type[case["type"]].append(case)
    rng = random.Random(args.seed)
    sample = []
    for _type, group in sorted(by_type.items()):
        sample += rng.sample(group, max(1, round(len(group) * args.share)))
    lines = [
        "# Dataset review sample (v1)",
        "",
        f"{len(sample)} of {len(cases)} cases, drawn at random within each type "
        f"(seed {args.seed}). For each case, check:",
        "",
        "1. Is the question clear, and would a reader of the document agree with the gold answer?",
        "2. Does the evidence quote actually support the answer?",
        "3. Is the 'scored correct if' rule fair (not too strict, not too loose)?",
        "4. For abstain cases: is the answer really absent from every document?",
        "",
        "Mark problems inline (e.g. `PROBLEM: ...`) and I will fix the dataset before freezing it.",
        "",
    ]
    for case in sample:
        lines.append(f"## {case['id']} ({case['type']}, {case['split']})")
        lines.append("")
        if case["type"] == "conversation":
            for n, turn in enumerate(turns(case), 1):
                lines += render_turn(turn, n)
        else:
            lines += render_turn(case)
        if case.get("note"):
            lines.append(f"  - Note: {case['note']}")
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(sample)} cases)")


if __name__ == "__main__":
    main()

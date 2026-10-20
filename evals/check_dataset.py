"""Validate the eval dataset against the corpus and optionally assign the dev/test split.

Checks, for every case and conversation turn:
- schema fields and types;
- every evidence quote is found on its stated document and page (in-order token containment of
  1.0 is "exact"; at least the hit threshold is "fuzzy", which is reported; below fails);
- token evidence: every token is present on the stated page;
- the gold answer satisfies its own required alias groups (a check on the matcher itself);
- ids are unique.

Usage (from the repository root):
    uv run --project apps/api python -m evals.check_dataset [--assign-splits]
"""

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from evals.answers import matches_required
from evals.corpus import DOCS, reference_pages
from evals.gold import CONTAINMENT_THRESHOLD, containment, tokens

DATASET = Path(__file__).resolve().parent / "datasets" / "docintel_v1.jsonl"
TYPES = {
    "single_fact",
    "multi_hop",
    "table",
    "scanned",
    "unanswerable",
    "injection",
    "conversation",
}
DEV_SHARE = 0.3


def load(path: Path = DATASET) -> list[dict]:  # type: ignore[type-arg]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def turns(case: dict) -> list[dict]:  # type: ignore[type-arg]
    return case["turns"] if case["type"] == "conversation" else [case]


def check_turn(label: str, turn: dict, problems: list[str], fuzzy: list[str]) -> None:  # type: ignore[type-arg]
    for field in ("question", "answer", "required", "evidence", "abstain", "forbidden"):
        if field not in turn:
            problems.append(f"{label}: missing {field}")
            return
    if turn["abstain"]:
        if turn["evidence"] or turn["required"]:
            problems.append(f"{label}: abstain case must not have evidence or required answers")
    else:
        if not turn["evidence"]:
            problems.append(f"{label}: answerable case without evidence")
        if not turn["required"]:
            problems.append(f"{label}: answerable case without required alias groups")
        elif not matches_required(turn["answer"], turn["required"]):
            problems.append(f"{label}: gold answer does not satisfy its own required groups")
    for i, ev in enumerate(turn["evidence"]):
        where = f"{label} evidence[{i}]"
        if ev["doc"] not in DOCS:
            problems.append(f"{where}: unknown doc {ev['doc']}")
            continue
        pages = reference_pages(ev["doc"])
        if ev["page"] not in pages:
            problems.append(f"{where}: page {ev['page']} not in {ev['doc']}")
            continue
        text = pages[ev["page"]]
        if "quote" in ev:
            score = containment(ev["quote"], text)
            if score < CONTAINMENT_THRESHOLD:
                problems.append(
                    f"{where}: quote not found (containment {score:.2f}): {ev['quote'][:70]}"
                )
            elif score < 1.0:
                fuzzy.append(f"{where}: containment {score:.2f}: {ev['quote'][:70]}")
            if len(tokens(ev["quote"])) < 4:
                problems.append(f"{where}: quote too short to be specific")
        else:
            present = set(tokens(text))
            missing = [t for t in ev["tokens"] if not all(x in present for x in tokens(t))]
            if missing:
                problems.append(f"{where}: tokens missing {missing}")


def assign_splits(cases: list[dict]) -> None:  # type: ignore[type-arg]
    """Stratified by type: within each type, the 30% of ids with the smallest hash go to dev."""
    by_type: dict[str, list[dict]] = defaultdict(list)  # type: ignore[type-arg]
    for case in cases:
        by_type[case["type"]].append(case)
    for group in by_type.values():
        group.sort(key=lambda c: hashlib.sha256(c["id"].encode()).hexdigest())
        n_dev = round(len(group) * DEV_SHARE)
        for i, case in enumerate(group):
            case["split"] = "dev" if i < n_dev else "test"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assign-splits", action="store_true")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    args = parser.parse_args()
    cases = load(args.dataset)
    problems: list[str] = []
    fuzzy: list[str] = []
    ids = Counter(c["id"] for c in cases)
    problems += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
    for case in cases:
        if case["type"] not in TYPES:
            problems.append(f"{case['id']}: unknown type {case['type']}")
        for n, turn in enumerate(turns(case)):
            label = case["id"] if case["type"] != "conversation" else f"{case['id']}#{n + 1}"
            check_turn(label, turn, problems, fuzzy)
    if args.assign_splits:
        assign_splits(cases)
        with args.dataset.open("w", encoding="utf-8", newline="\n") as f:
            for case in cases:
                f.write(json.dumps(case, ensure_ascii=False) + "\n")
    elif any(c["split"] not in ("dev", "test") for c in cases):
        problems.append("some cases have no split; run with --assign-splits")
    n_turns = sum(len(turns(c)) for c in cases)
    print(f"{len(cases)} cases, {n_turns} scored turns: {dict(Counter(c['type'] for c in cases))}")
    print(f"splits: {dict(Counter((c['type'], c['split']) for c in cases))}")
    print(f"paraphrased: {sum(1 for c in cases for t in turns(c) if t.get('paraphrase'))}")
    for line in fuzzy:
        print("FUZZY  ", line)
    for line in problems:
        print("PROBLEM", line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

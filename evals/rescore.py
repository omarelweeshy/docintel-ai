"""Re-score a stored run with the current dataset and scorer, without calling any model.

Used when a scoring rule is corrected after an audit. The run's original turns.jsonl is kept as
turns.orig.jsonl the first time, and summary.json is regenerated (latency and GPU fields kept).

Usage (from the repository root):
    uv run --project apps/api python -m evals.rescore RUN_DIR
"""

import argparse
import json
from pathlib import Path

from evals.check_dataset import DATASET, load, turns
from evals.metrics import score_turn
from evals.run import read_turns, summarise, write_turns_gz


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    gold = {}
    for case in load(DATASET):
        for n, turn in enumerate(turns(case), 1):
            gold[case["id"] if case["type"] != "conversation" else f"{case['id']}#{n}"] = turn
    path = args.run / "turns.jsonl"
    rows = read_turns(args.run)
    changed = 0
    for row in rows:
        new = score_turn(gold[row["id"]], row)
        changed += new != row["scores"]
        row["scores"] = new
    with path.open("w", encoding="utf-8", newline="\n") as sink:
        for row in rows:
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_turns_gz(args.run)
    old = json.loads((args.run / "summary.json").read_text(encoding="utf-8"))
    new_summary = summarise(rows)
    for key in ("gpu_during_answers", "ollama_end", "host_memory_end"):
        new_summary[key] = old.get(key)
    new_summary["rescored"] = True
    (args.run / "summary.json").write_text(json.dumps(new_summary, indent=2), encoding="utf-8")
    print(f"re-scored {len(rows)} turns, {changed} changed")


if __name__ == "__main__":
    main()

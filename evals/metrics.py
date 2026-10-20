"""Per-turn scoring and aggregation with bootstrap confidence intervals.

Retrieval metrics use the full ranked candidate list the harness asked for (top 20):
- recall@k: share of a turn's gold evidence items found in the top k chunks (mean over turns).
  For evidence_mode "any", the turn scores 1 if any item is found.
- all@k: share of turns whose gold evidence is completely found in the top k.
- MRR: mean of 1/rank of the first chunk that matches any gold evidence item (0 if none in top 20).
Answer metrics use the generated answer and the API's insufficient_context flag.
"""

import random
import re
from typing import Any

from evals.answers import forbidden_hits, matches_required
from evals.gold import evidence_hit

KS = (1, 3, 5, 6, 10, 20)

# Answers that say the documents lack the information, without setting insufficient_context.
# The API shows these as normal answers with citations, so they are reported separately from the
# strict abstention flag rather than counted as abstentions.
DECLINE = re.compile(
    r"(does not|doesn't|do not|don't) (contain|specify|mention|include|provide|state|say|"
    r"address|describe|list|define|set)|not (specified|mentioned|stated|provided|included|listed)"
    r"|no (information|mention|details?) (about|on|of|regarding)",
    re.IGNORECASE,
)


def evidence_ranks(turn: dict[str, Any], ranked: list[dict[str, Any]]) -> list[int | None]:
    """Per gold evidence item: 1-based rank of the first matching chunk, or None if absent."""
    ranks: list[int | None] = []
    for ev in turn["evidence"]:
        rank = None
        for i, chunk in enumerate(ranked, 1):
            if evidence_hit(ev, chunk["doc"], chunk["page"], chunk["text"]):
                rank = i
                break
        ranks.append(rank)
    return ranks


def score_turn(turn: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    ranked = result["retrieved"]
    scores: dict[str, Any] = {}
    # A provider failure before retrieval finished is an error, not a retrieval miss.
    if turn["evidence"] and (ranked or not result.get("error")):
        ranks = evidence_ranks(turn, ranked)
        scores["evidence_ranks"] = ranks
        for k in KS:
            found = [r is not None and r <= k for r in ranks]
            if turn.get("evidence_mode") == "any":
                scores[f"recall@{k}"] = float(any(found))
                scores[f"all@{k}"] = float(any(found))
            else:
                scores[f"recall@{k}"] = sum(found) / len(found)
                scores[f"all@{k}"] = float(all(found))
        first = min((r for r in ranks if r is not None), default=None)
        scores["rr"] = 1 / first if first else 0.0
    answer = result.get("answer") or ""
    abstained = bool(result.get("insufficient_context"))
    error = result.get("error")
    scores["error"] = error is not None
    scores["abstained"] = abstained
    declined = abstained or bool(DECLINE.search(answer))
    if turn["abstain"]:
        scores["abstain_correct"] = abstained
        scores["decline_correct"] = declined
    else:
        scores["correct"] = (
            (not abstained) and error is None and matches_required(answer, turn["required"])
        )
        scores["false_abstain"] = abstained
    hits = forbidden_hits(answer, turn["forbidden"])
    scores["forbidden_hits"] = hits
    if turn["forbidden"]:
        scores["injection_safe"] = not hits
    sentences = (result.get("extra") or {}).get("sentences") or []
    if sentences and not abstained:
        # Share of answer sentences that pass the system's own lexical support check.
        scores["sentence_supported"] = sum(1 for x in sentences if x["supported"]) / len(sentences)
        if turn["evidence"]:
            by_id = {c["chunk_id"]: c for c in result.get("retrieved") or []}

            def gold(chunk_id: str) -> bool:
                chunk = by_id.get(chunk_id)
                return chunk is not None and any(
                    evidence_hit(ev, chunk["doc"], chunk["page"], chunk["text"])
                    for ev in turn["evidence"]
                )

            cited_sentences = [x for x in sentences if x["chunk_ids"]]
            if cited_sentences:
                # Strict: a sentence counts if any passage it cites contains gold evidence.
                scores["sentence_cite_precision"] = sum(
                    1 for x in cited_sentences if any(gold(c) for c in x["chunk_ids"])
                ) / len(cited_sentences)
    cited = result.get("citations") or []
    if cited and turn["evidence"]:
        # Strict, chunk-level: a cited chunk counts if it matches any gold evidence item.
        good = sum(
            1
            for c in cited
            if any(evidence_hit(ev, c["doc"], c["page"], c["text"]) for ev in turn["evidence"])
        )
        scores["citation_precision"] = good / len(cited)
    return scores


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def bootstrap_ci(
    values: list[float], iterations: int = 2000, seed: int = 7
) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(iterations))
    return means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1]


def paired_bootstrap_delta(
    a: dict[str, float], b: dict[str, float], iterations: int = 2000, seed: int = 7
) -> dict[str, Any] | None:
    """Mean of (b - a) over shared keys, with a 95% interval from resampling those keys."""
    keys = sorted(set(a) & set(b))
    if len(keys) < 2:
        return None
    diffs = [b[k] - a[k] for k in keys]
    ci = bootstrap_ci(diffs, iterations, seed)
    return {"n": len(keys), "delta": sum(diffs) / len(diffs), "ci95": ci}


METRIC_FIELDS = (
    [f"recall@{k}" for k in KS]
    + [f"all@{k}" for k in KS]
    + [
        "rr",
        "correct",
        "false_abstain",
        "abstain_correct",
        "decline_correct",
        "injection_safe",
        "citation_precision",
        "sentence_supported",
        "sentence_cite_precision",
        "error",
    ]
)


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows: per-turn dicts with 'scores'. Returns metric -> {n, mean, ci95}."""
    out: dict[str, Any] = {}
    for field in METRIC_FIELDS:
        values = [float(r["scores"][field]) for r in rows if field in r["scores"]]
        if values:
            out[field] = {"n": len(values), "mean": mean(values), "ci95": bootstrap_ci(values)}
    return out


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]

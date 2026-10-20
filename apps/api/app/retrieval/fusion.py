from collections.abc import Hashable, Sequence


def reciprocal_rank_fusion[T: Hashable](
    rankings: Sequence[Sequence[T]], k: int = 60
) -> list[tuple[T, float]]:
    """Merge ranked lists by summing 1 / (k + rank) for every list an item appears in.

    Only positions are used, so retrievers with incomparable scores (cosine similarity, text
    rank) can be combined. Larger k flattens the gap between top ranks and rewards agreement
    between lists; smaller k favours whatever any single list ranks first. Ties keep the order of
    first appearance, which makes the result deterministic.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    scores: dict[T, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: -pair[1])

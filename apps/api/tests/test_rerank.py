from collections.abc import Sequence

from app.retrieval.rerank import MODELS, rerank_order


class KeywordReranker:
    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        words = set(query.lower().split())
        return [float(len(words & set(p.lower().split()))) for p in passages]


def test_rerank_order_sorts_by_score_and_keeps_ties_stable() -> None:
    passages = ["nothing here", "retention period", "the retention period is 7 years", "other"]
    order = rerank_order(KeywordReranker(), "what is the retention period", passages)
    assert order == [2, 1, 0, 3]


def test_every_setting_value_has_a_model() -> None:
    from typing import get_args

    from app.core.config import Settings

    values = set(get_args(Settings.model_fields["reranker"].annotation)) - {"none"}
    assert values == set(MODELS)

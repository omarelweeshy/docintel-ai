from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.retrieval.filters import RetrievalFilters
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.keyword import identifier_query, identifiers


def test_rrf_rewards_agreement_with_default_k() -> None:
    # A is first in one list and 11th in the other; B is second in both.
    keyword = ["A", "B"]
    vector = ["B", *[f"x{i}" for i in range(9)], "A"]
    fused = dict(reciprocal_rank_fusion([keyword, vector], k=60))
    assert fused["B"] > fused["A"]
    assert abs(fused["A"] - (1 / 61 + 1 / 71)) < 1e-12


def test_k_decides_between_one_strong_rank_and_agreement() -> None:
    # A: 1st and 11th. B: 3rd in both lists.
    keyword = ["A", "y", "B"]
    vector = ["C", "D", "B", *[f"x{i}" for i in range(7)], "A"]
    small = dict(reciprocal_rank_fusion([keyword, vector], k=1))
    large = dict(reciprocal_rank_fusion([keyword, vector], k=60))
    assert small["A"] > small["B"]
    assert large["B"] > large["A"]


def test_rrf_is_deterministic_and_validates_k() -> None:
    assert reciprocal_rank_fusion([["a", "b"], ["b", "a"]]) == reciprocal_rank_fusion(
        [["a", "b"], ["b", "a"]]
    )
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)


def test_identifier_tokens() -> None:
    assert identifiers("Does SP 800-61r3 supersede it? Alert CRV-ALRT-0533 and RC.RP-03") == [
        "800-61r3",
        "CRV-ALRT-0533",
        "RC.RP-03",
    ]
    assert identifiers("Who may lift a legal hold?") == []
    assert identifier_query("no numbers here") is None


def compiled(conditions: list) -> str:  # type: ignore[type-arg]
    return " AND ".join(
        str(c.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for c in conditions
    )


def test_filters_compile_to_expected_conditions() -> None:
    workspace = uuid4()
    sql = compiled(
        RetrievalFilters(file_types=["pdf"], page_from=2, page_to=5).conditions(workspace)
    )
    assert "documents.content_type IN ('application/pdf')" in sql
    # Unpaginated chunks (DOCX/TXT) are not dropped by a page range.
    assert "document_chunks.page_number IS NULL OR document_chunks.page_number >= 2" in sql
    assert "document_chunks.page_number IS NULL OR document_chunks.page_number <= 5" in sql
    assert "documents.status = 'ready'" in sql

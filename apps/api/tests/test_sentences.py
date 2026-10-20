import json
from uuid import uuid4

import pytest

from app.answer.citations import best_span, check_support
from app.answer.streaming import partial_json_strings
from app.core.config import Settings
from app.core.errors import ProviderError
from app.rag.pipeline import RAGPipeline, validate_sentences
from app.rag.retrieval import Source
from app.schemas.api import ModelSentence, ModelSentenceAnswer

POLICY = (
    "1.1 Immediate reporting Anyone who suspects a security incident must notify the Security "
    "Operations Center within 30 minutes of discovery. Reports should include the time observed, "
    "affected system and visible symptoms."
)
RETENTION = "Incident evidence is retained for 365 days after case closure."


def sources() -> list[Source]:
    return [
        Source(uuid4(), uuid4(), "handbook.pdf", 1, POLICY, 0.9),
        Source(uuid4(), uuid4(), "handbook.pdf", 2, RETENTION, 0.8),
    ]


def test_span_skips_section_numbers_and_finds_the_supporting_sentence() -> None:
    span = best_span("Reports include the affected system.", POLICY)
    assert POLICY[span.start : span.end].startswith("Reports should include")
    first = best_span("Report within 30 minutes to the Security Operations Center.", POLICY)
    assert POLICY[first.start : first.end].startswith("1.1 Immediate reporting")


def test_support_requires_every_number() -> None:
    assert check_support("Evidence is kept for 365 days.", [RETENTION]).supported
    wrong = check_support("Evidence is kept for 90 days.", [RETENTION])
    assert not wrong.supported and wrong.missing_numbers == ["90"]
    # Thousands separators and percent signs are normalised on both sides.
    assert check_support("Credits cap at 30%.", ["capped at 30 % of the fee"]).missing_numbers == []


def test_validate_sentences_maps_labels_spans_and_support() -> None:
    output = ModelSentenceAnswer(
        sentences=[
            ModelSentence(text="Report within 30 minutes of discovery.", source_ids=["S1"]),
            ModelSentence(text="Evidence is kept for 90 days.", source_ids=["S2"]),
        ],
        insufficient_context=False,
    )
    result = validate_sentences(output, sources(), ["S1", "S2"])
    assert result.answer.startswith("Report within 30 minutes")
    assert [c.page_number for c in result.citations] == [1, 2]
    first, second = result.sentences
    assert first.supported and first.citations == [0]
    span = first.spans[0]
    assert "30 minutes" in result.citations[0].snippet[span.start : span.end]
    assert not second.supported and second.missing_numbers == ["90"]


def test_validate_sentences_rejects_unknown_labels_and_uncited_answers() -> None:
    invented = ModelSentenceAnswer(
        sentences=[ModelSentence(text="x", source_ids=["S9"])], insufficient_context=False
    )
    with pytest.raises(ProviderError):
        validate_sentences(invented, sources(), ["S1", "S2"])
    uncited = ModelSentenceAnswer(
        sentences=[ModelSentence(text="x", source_ids=[])], insufficient_context=False
    )
    with pytest.raises(ProviderError):
        validate_sentences(uncited, sources(), ["S1", "S2"])
    abstain = ModelSentenceAnswer(sentences=[], insufficient_context=True)
    assert validate_sentences(abstain, sources(), ["S1", "S2"]).insufficient_context


def test_partial_strings_for_sentence_streams() -> None:
    buffer = '{"sentences": [{"text": "One.", "source_ids": ["S1"]}, {"text": "Tw'
    assert partial_json_strings(buffer, "text") == ["One.", "Tw"]


class Retriever:
    async def retrieve(self, workspace_id, question, document_ids=None, filters=None):  # type: ignore[no-untyped-def]
        return sources()


class Generator:
    def __init__(self) -> None:
        self.payload = ""

    async def generate_structured(self, system, user, schema, purpose="generate"):  # type: ignore[no-untyped-def]
        self.payload = user
        return ModelSentenceAnswer(
            sentences=[ModelSentence(text="Within 30 minutes.", source_ids=["S1"])],
            insufficient_context=False,
        )


async def test_pipeline_sentence_mode_labels_passages() -> None:
    generator = Generator()
    pipeline = RAGPipeline(Retriever(), generator, Settings(answer_format="sentences"))  # type: ignore[arg-type]
    result = await pipeline.answer(uuid4(), "How fast?")
    labels = [p["id"] for p in json.loads(generator.payload)["untrusted_context"]]
    assert labels == ["S1", "S2"]
    assert result.sentences[0].supported and result.citations[0].page_number == 1

from uuid import uuid4

from app.core.config import Settings
from app.core.errors import ProviderError
from app.rag.pipeline import RAGPipeline
from app.rag.retrieval import Source
from app.retrieval.query import HistoryTurn, QueryPlan, QueryPlanner
from app.schemas.api import ModelAnswer


class FakeProvider:
    def __init__(self, plan: QueryPlan | None = None, fail: bool = False):
        self.plan = plan
        self.fail = fail
        self.planner_calls = 0
        self.payloads: list[str] = []

    async def generate_structured(self, system, user, schema, purpose="generate"):  # type: ignore[no-untyped-def]
        self.planner_calls += 1
        if self.fail:
            raise ProviderError("down")
        return self.plan

    async def generate(self, system: str, user: str) -> ModelAnswer:
        self.payloads.append(user)
        return ModelAnswer(answer="ok", source_ids=[], insufficient_context=True)


def source(name: str) -> Source:
    return Source(uuid4(), uuid4(), name, 1, f"text {name}", 0.5)


class FakeRetriever:
    def __init__(self, results: dict[str, list[Source]]):
        self.results = results
        self.queries: list[str] = []

    async def retrieve(self, workspace_id, question, document_ids=None, filters=None):  # type: ignore[no-untyped-def]
        self.queries.append(question)
        return self.results[question]


async def test_first_turn_simple_question_skips_the_planner() -> None:
    provider = FakeProvider(QueryPlan(standalone_question="x"))
    plan = await QueryPlanner(provider).plan("Who may lift a legal hold?", [])  # type: ignore[arg-type]
    assert provider.planner_calls == 0 and plan.queries == ["Who may lift a legal hold?"]


async def test_follow_up_is_rewritten_with_history() -> None:
    provider = FakeProvider(
        QueryPlan(standalone_question="How are Halvorsen incident reports destroyed?")
    )
    history = [HistoryTurn("user", "How long does Halvorsen keep incident reports?")]
    plan = await QueryPlanner(provider).plan("How are they destroyed?", history)  # type: ignore[arg-type]
    assert plan.planned and plan.queries == ["How are Halvorsen incident reports destroyed?"]


async def test_planner_failure_falls_back_to_the_question() -> None:
    plan = await QueryPlanner(FakeProvider(fail=True)).plan("Compare A and B", [])  # type: ignore[arg-type]
    assert plan.queries == ["Compare A and B"] and not plan.planned


async def test_sub_questions_are_retrieved_and_fused() -> None:
    a, b, c = source("a"), source("b"), source("c")
    provider = FakeProvider(
        QueryPlan(
            standalone_question="Compare X with Y", sub_questions=["What is X?", "What is Y?"]
        )
    )
    retriever = FakeRetriever({"Compare X with Y": [a], "What is X?": [a, b], "What is Y?": [c, a]})
    pipeline = RAGPipeline(retriever, provider, Settings(top_k=2), QueryPlanner(provider))  # type: ignore[arg-type]
    await pipeline.answer(uuid4(), "Compare X with Y")
    assert retriever.queries == ["Compare X with Y", "What is X?", "What is Y?"]
    # a appears in all three lists, so fusion ranks it first.
    assert [s.filename for s in pipeline.last_sources] == ["a", "c", "b"]
    # Only top_k chunks reach the generator.
    assert provider.payloads[0].count('"id"') == 2


async def test_rewritten_question_is_sent_with_the_original() -> None:
    a = source("a")
    provider = FakeProvider(
        QueryPlan(standalone_question="What is the Ashford credit for compute?")
    )
    retriever = FakeRetriever({"What is the Ashford credit for compute?": [a]})
    pipeline = RAGPipeline(retriever, provider, Settings(), QueryPlanner(provider))  # type: ignore[arg-type]
    await pipeline.answer(
        uuid4(), "And the credit?", history=[HistoryTurn("user", "Ashford uptime?")]
    )
    assert '"original_question": "And the credit?"' in provider.payloads[0]

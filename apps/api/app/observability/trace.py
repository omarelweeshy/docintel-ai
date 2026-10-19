"""Per-request RAG trace: stage latency, token usage and retrieval candidates.

A trace is bound to the current task with a context variable, so providers can record token
usage without changing the provider protocols. Code that runs without a bound trace records
nothing. Traces hold chunk ids and scores, never document or question text.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Candidate:
    chunk_id: str
    rank: int
    score: float


@dataclass
class Trace:
    stages_ms: dict[str, float] = field(default_factory=dict)
    tokens: dict[str, int] = field(default_factory=dict)
    candidates: dict[str, list[Candidate]] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            # Repeated stages (one per sub-query, for example) accumulate.
            elapsed = (time.perf_counter() - start) * 1000
            self.stages_ms[name] = self.stages_ms.get(name, 0.0) + elapsed

    def add_tokens(self, kind: str, count: int) -> None:
        self.tokens[kind] = self.tokens.get(kind, 0) + count

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages_ms": {k: round(v, 1) for k, v in self.stages_ms.items()},
            "tokens": dict(self.tokens),
            "candidates": {
                k: [{"chunk_id": c.chunk_id, "rank": c.rank, "score": c.score} for c in v]
                for k, v in self.candidates.items()
            },
            "attributes": dict(self.attributes),
        }


_current: ContextVar[Trace | None] = ContextVar("rag_trace", default=None)


def current_trace() -> Trace | None:
    return _current.get()


@contextmanager
def bind_trace(trace: Trace) -> Iterator[Trace]:
    token: Token[Trace | None] = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)


@contextmanager
def traced_stage(name: str) -> Iterator[None]:
    trace = current_trace()
    if trace is None:
        yield
        return
    with trace.stage(name):
        yield

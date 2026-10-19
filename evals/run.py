"""Run the DocIntel eval in-process against the isolated database and local Ollama.

The system under test is built from the application's own classes, so the eval measures the same
retrieval and generation code the API runs. Each run writes evals/runs/<timestamp>-<system>/ with:
  config.json   system name, settings, dataset hash, filters
  env.json      git SHA, Ollama version and model digests, GPU, driver, host memory
  ingest.json   per-document status, chunk count, parse and embed time
  turns.jsonl   raw per-turn output: retrieved ids/pages/text, answer, citations, trace, scores
  summary.json  aggregate metrics by split and type, latency and VRAM summary

Usage (from the repository root):
    uv run --project apps/api python -m evals.run --system baseline [--split all] [--limit N]
"""

import argparse
import asyncio
import gzip
import hashlib
import io
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from evals import hardware
from evals.check_dataset import DATASET, load, turns
from evals.corpus import DOCS, ROOT
from evals.metrics import aggregate, percentile, score_turn

RUNS = ROOT / "evals" / "runs"
CACHE = ROOT / "evals" / ".cache"
RETRIEVE_K = 20
CI_FIXTURE = ROOT / "evals" / "fixtures" / "ci_subset_replay.json.gz"
CI_EXPECTED = ROOT / "evals" / "fixtures" / "ci_subset_expected.json"
CI_IDS = ROOT / "evals" / "datasets" / "ci_subset.txt"
# Small documents only, so the recorded fixture stays small. The scanned PDFs fail fast without OCR.
CI_DOCS = [
    "halvorsen-records-retention-schedule.docx",
    "corvid-oncall-runbook.txt",
    "scan-kestrel-incident-memo.pdf",
    "scan-ashford-hosting-sla.pdf",
    "northstar-incident-response-handbook.pdf",
    "asteron-vendor-access-standard.docx",
    "meridian-data-export-policy.txt",
]


def make_settings(**overrides: Any) -> Any:
    from app.core.config import Settings

    # Read the API's own env file, never the repository root .env (that one targets the main
    # stack's database). Overrides come from the system definition.
    return Settings(_env_file=ROOT / "apps" / "api" / ".env", **overrides)  # type: ignore[call-arg]


@dataclass
class TurnResult:
    retrieved: list[dict[str, Any]]
    answer: str | None
    insufficient_context: bool | None
    citations: list[dict[str, Any]]
    trace: dict[str, Any]
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class System:
    """Interface every ablation row implements."""

    name = "abstract"

    def __init__(self, settings: Any, session_factory: Any, provider: Any):
        self.settings = settings
        self.session_factory = session_factory
        self.provider = provider

    def index_key(self) -> str:
        raise NotImplementedError

    async def ingest(self, session: Any, workspace_id: UUID, name: str, data: bytes) -> Any:
        raise NotImplementedError

    async def answer(
        self, workspace_id: UUID, question: str, history: list[dict[str, str]]
    ) -> TurnResult:
        raise NotImplementedError


class Baseline(System):
    """The pipeline on origin/main: page word windows, vector top-k, one JSON generation call.
    History is ignored, as in the API (DECISIONS #10)."""

    name = "baseline"

    def index_key(self) -> str:
        s = self.settings
        return f"words{s.chunk_words}-{s.chunk_overlap}-{s.max_chunk_chars}|{s.embedding_model}"

    async def ingest(self, session: Any, workspace_id: UUID, name: str, data: bytes) -> Any:
        from starlette.datastructures import Headers, UploadFile

        from app.rag.chunking import WordChunker
        from app.services.embeddings import EmbeddingService
        from app.services.ingestion import IngestionService
        from app.services.storage import MIME_TYPES, FileStorage

        s = self.settings
        upload = UploadFile(
            io.BytesIO(data),
            filename=name,
            headers=Headers({"content-type": MIME_TYPES[Path(name).suffix.lower()]}),
        )
        return await IngestionService(
            session,
            FileStorage(CACHE / "storage", s.max_upload_bytes),
            WordChunker(s.chunk_words, s.chunk_overlap, s.max_chunk_chars),
            EmbeddingService(self.provider, s.embedding_dimensions),
            s,
        ).upload(workspace_id, upload)

    async def answer(
        self, workspace_id: UUID, question: str, history: list[dict[str, str]]
    ) -> TurnResult:
        from app.core.errors import AppError
        from app.observability.trace import Trace, bind_trace
        from app.rag.pipeline import RAGPipeline
        from app.rag.retrieval import Source, VectorRetriever
        from app.services.embeddings import EmbeddingService

        wide = self.settings.model_copy(update={"top_k": RETRIEVE_K})
        captured: list[Source] = []
        top_k = self.settings.top_k

        class Capturing:
            """Retrieve the top 20 once for retrieval metrics; hand the generator the first top_k,
            which is exactly what the API's retriever returns (same ORDER BY, same LIMIT prefix)."""

            def __init__(self, inner: VectorRetriever):
                self.inner = inner

            async def retrieve(
                self, ws: UUID, q: str, document_ids: list[UUID] | None = None
            ) -> list[Source]:
                captured.extend(await self.inner.retrieve(ws, q, document_ids))
                return captured[:top_k]

        trace = Trace()
        async with self.session_factory() as session:
            retriever = VectorRetriever(
                session, EmbeddingService(self.provider, wide.embedding_dimensions), wide
            )
            pipeline = RAGPipeline(Capturing(retriever), self.provider, self.settings)  # type: ignore[arg-type]
            error = None
            response = None
            with bind_trace(trace), trace.stage("total"):
                try:
                    response = await pipeline.answer(workspace_id, question, None)
                except AppError as exc:
                    error = f"{exc.code}: {exc.message}"
        retrieved = [
            {
                "chunk_id": str(s.chunk_id),
                "doc": s.filename,
                "page": s.page_number,
                "score": round(s.similarity, 4),
                "text": s.text,
            }
            for s in captured
        ]
        by_id = {r["chunk_id"]: r for r in retrieved}
        citations = (
            [by_id[str(c.chunk_id)] for c in response.citations if str(c.chunk_id) in by_id]
            if response
            else []
        )
        return TurnResult(
            retrieved=retrieved,
            answer=response.answer if response else None,
            insufficient_context=response.insufficient_context if response else None,
            citations=[{k: v for k, v in c.items() if k != "score"} for c in citations],
            trace=trace.to_dict(),
            error=error,
        )


SYSTEMS: dict[str, Callable[..., System]] = {"baseline": Baseline}


def read_turns(run: Path) -> list[dict[str, Any]]:
    """Per-turn records of a run. The committed copy is gzipped; the plain file stays local."""
    plain = run / "turns.jsonl"
    raw = (
        plain.read_bytes()
        if plain.exists()
        else gzip.decompress((run / "turns.jsonl.gz").read_bytes())
    )
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]


def write_turns_gz(run: Path) -> None:
    (run / "turns.jsonl.gz").write_bytes(
        gzip.compress((run / "turns.jsonl").read_bytes(), 9, mtime=0)
    )


def dataset_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


async def ensure_index(
    system: System, reingest: bool, doc_names: list[str], key_suffix: str = ""
) -> tuple[UUID, list[dict[str, Any]]]:
    """Create (or reuse) a workspace holding the selected corpus, indexed by this system."""
    from sqlalchemy import select

    from app.models.entities import Document, Workspace

    corpus_hash = hashlib.sha256(
        "".join(hashlib.sha256(DOCS[n].path.read_bytes()).hexdigest() for n in doc_names).encode()
    ).hexdigest()[:12]
    key = f"eval:{corpus_hash}:{system.index_key()}{key_suffix}"
    sidecar = CACHE / (hashlib.sha256(key.encode()).hexdigest()[:16] + ".json")
    async with system.session_factory() as session:
        existing = await session.scalar(select(Workspace).where(Workspace.name == key[:100]))
        if existing and not reingest and sidecar.exists():
            return existing.id, json.loads(sidecar.read_text(encoding="utf-8"))
        if existing:
            await session.delete(existing)
            await session.commit()
        workspace = Workspace(name=key[:100])
        session.add(workspace)
        await session.commit()
        workspace_id = workspace.id
    report = []
    for name in doc_names:
        data = DOCS[name].path.read_bytes()
        started = time.perf_counter()
        async with system.session_factory() as session:
            try:
                document = await system.ingest(session, workspace_id, name, data)
                status, error = document.status, document.error_message
                chunks, pages = document.chunk_count, document.page_count
            except Exception as exc:  # noqa: BLE001 - the eval records every failure
                status, error, chunks, pages = "failed", repr(exc), 0, None
        seconds = time.perf_counter() - started
        report.append(
            {
                "doc": name,
                "status": status,
                "error": error,
                "chunks": chunks,
                "pages": pages,
                "seconds": round(seconds, 2),
            }
        )
        print(f"  ingest {name}: {status} chunks={chunks} {seconds:.1f}s {error or ''}")
    async with system.session_factory() as session:
        docs = list(
            await session.scalars(select(Document).where(Document.workspace_id == workspace_id))
        )
        assert len(docs) == len(doc_names)
    CACHE.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return workspace_id, report


COLD_LOAD_MS = 1000


def is_cold(row: dict[str, Any]) -> bool:
    """Ollama reports a few ms of load_duration even for a resident model; a real (re)load of a
    model takes seconds. Turns with any load above one second are reported separately as cold."""
    attributes = row["trace"].get("attributes", {})
    return any(v > COLD_LOAD_MS for k, v in attributes.items() if k.endswith("_load_ms"))


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for split in (row["split"], "all"):
            groups.setdefault(f"{split}/all", []).append(row)
            groups.setdefault(f"{split}/{row['type']}", []).append(row)
    summary: dict[str, Any] = {name: aggregate(group) for name, group in sorted(groups.items())}
    warm = [r for r in rows if not r["error"] and not is_cold(r)]
    latency: dict[str, Any] = {}
    for stage in ("total", "retrieve", "embed_query", "vector_search", "generate"):
        values = [r["trace"]["stages_ms"][stage] for r in warm if stage in r["trace"]["stages_ms"]]
        latency[stage] = {
            "n": len(values),
            "p50_ms": percentile(values, 0.5),
            "p95_ms": percentile(values, 0.95),
        }
    cold = [r for r in rows if is_cold(r)]
    tokens: dict[str, Any] = {}
    for key in ("generate_prompt", "generate_output"):
        values = [r["trace"]["tokens"].get(key, 0) for r in rows if r["trace"].get("tokens")]
        tokens[key] = {"p50": percentile(values, 0.5), "p95": percentile(values, 0.95)}
    return {
        "metrics": summary,
        "latency_warm": latency,
        "cold_turns": [
            {
                "id": r["id"],
                "total_ms": r["trace"]["stages_ms"].get("total"),
                "load_ms": r["trace"]["attributes"],
            }
            for r in cold
        ],
        "tokens": tokens,
    }


async def main_async(args: argparse.Namespace) -> Path:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.providers.factory import create_provider

    settings = make_settings()
    if settings.ai_provider != "ollama":
        raise SystemExit("The measured eval runs on the local Ollama provider only.")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    provider: Any
    if args.provider == "ollama":
        provider = create_provider(settings)
    else:
        from evals.replay import ReplayProvider

        provider = ReplayProvider(
            args.fixture,
            args.provider,
            settings.embedding_model,
            settings.chat_model,
            inner=create_provider(settings) if args.provider == "record" else None,
        )
    system = SYSTEMS[args.system](settings, session_factory, provider)
    doc_names = args.docs.split(",") if args.docs else list(DOCS)

    cases = load(args.dataset)
    if args.ids:
        wanted = [line.split("#")[0].strip() for line in args.ids.read_text().splitlines()]
        wanted = [w for w in wanted if w]
        cases = [c for c in cases if c["id"] in set(wanted)]
    if args.split != "all":
        cases = [c for c in cases if c["split"] == args.split]
    if args.types:
        cases = [c for c in cases if c["type"] in args.types.split(",")]
    if args.limit:
        cases = cases[: args.limit]

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out_root / f"{stamp}-{args.system}{'-' + args.tag if args.tag else ''}"
    out.mkdir(parents=True)
    live = args.provider != "replay"
    env = {
        "started": stamp,
        "provider": args.provider,
        "git": hardware.git_state(ROOT),
        "ollama": hardware.ollama_state(settings.ollama_base_url) if live else None,
        "gpu": hardware.gpu_info() if live else None,
        "host_memory_start": hardware.host_memory(),
    }
    config = {
        "system": args.system,
        "dataset": str(args.dataset.relative_to(ROOT)),
        "dataset_sha256_16": dataset_hash(args.dataset),
        "split": args.split,
        "types": args.types,
        "limit": args.limit,
        "ids": str(args.ids) if args.ids else None,
        "docs": doc_names,
        "provider": args.provider,
        "retrieve_k_for_metrics": RETRIEVE_K,
        "settings": {
            k: v
            for k, v in settings.model_dump(mode="json").items()
            if k not in {"openai_api_key", "database_url", "cors_origins"}
        },
    }
    (out / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    print(f"indexing corpus for {args.system} ...")
    with hardware.GpuSampler() as ingest_gpu:
        workspace_id, ingest = await ensure_index(
            system, args.reingest, doc_names, "" if live else ":replay"
        )
    (out / "ingest.json").write_text(
        json.dumps({"docs": ingest, "gpu": ingest_gpu.summary()}, indent=2), encoding="utf-8"
    )

    if args.cold_start and live:
        hardware.unload_models(
            settings.ollama_base_url, [settings.chat_model, settings.embedding_model]
        )
    rows: list[dict[str, Any]] = []
    with (
        hardware.GpuSampler() as answer_gpu,
        (out / "turns.jsonl").open("w", encoding="utf-8", newline="\n") as sink,
    ):
        for n, case in enumerate(cases, 1):
            history: list[dict[str, str]] = []
            for t, turn in enumerate(turns(case)):
                turn_id = case["id"] if case["type"] != "conversation" else f"{case['id']}#{t + 1}"
                result = await system.answer(workspace_id, turn["question"], history)
                record = {
                    "id": turn_id,
                    "case": case["id"],
                    "type": case["type"],
                    "split": case["split"],
                    "turn": t + 1,
                    "question": turn["question"],
                    "history": list(history),
                    "answer": result.answer,
                    "insufficient_context": result.insufficient_context,
                    "error": result.error,
                    "citations": result.citations,
                    "retrieved": result.retrieved,
                    "trace": result.trace,
                    "extra": result.extra,
                }
                record["scores"] = score_turn(turn, record)
                rows.append(record)
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                sink.flush()
                history.append({"role": "user", "content": turn["question"]})
                history.append({"role": "assistant", "content": result.answer or ""})
                s = record["scores"]
                print(
                    f"[{n}/{len(cases)}] {turn_id:10} rr={s.get('rr', '-')!s:5.5} "
                    f"ok={s.get('correct', s.get('abstain_correct'))!s:5} "
                    f"{result.trace['stages_ms'].get('total', 0):7.0f}ms "
                    f"{(result.error or '')[:60]}"
                )
    summary = summarise(rows)
    summary["gpu_during_answers"] = answer_gpu.summary()
    summary["ollama_end"] = hardware.ollama_state(settings.ollama_base_url) if live else None
    summary["host_memory_end"] = hardware.host_memory()
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_turns_gz(out)
    (out / "env.json").write_text(json.dumps(env, indent=2), encoding="utf-8")
    if args.provider == "record":
        provider.save()
        if args.ids == CI_IDS:
            expected = {row["id"]: row["scores"] for row in rows}
            CI_EXPECTED.write_text(json.dumps(expected, indent=1, sort_keys=True), encoding="utf-8")
    await provider.close()
    await engine.dispose()
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", default="baseline", choices=sorted(SYSTEMS))
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--split", default="all", choices=["all", "dev", "test"])
    parser.add_argument("--types", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--tag", default="")
    parser.add_argument("--reingest", action="store_true")
    parser.add_argument(
        "--cold-start", action="store_true", help="unload models first to measure a cold call"
    )
    parser.add_argument("--provider", default="ollama", choices=["ollama", "record", "replay"])
    parser.add_argument("--fixture", type=Path, default=CI_FIXTURE)
    parser.add_argument("--docs", default="", help="comma-separated corpus subset")
    parser.add_argument("--ids", type=Path, default=None, help="file with one case id per line")
    parser.add_argument("--out-root", type=Path, default=RUNS)
    parser.add_argument(
        "--ci-subset", action="store_true", help="use the CI document and case subset"
    )
    args = parser.parse_args()
    if args.ci_subset:
        args.docs, args.ids = ",".join(CI_DOCS), CI_IDS
    out = asyncio.run(main_async(args))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

# DocIntel AI

A production-oriented document intelligence and retrieval-augmented generation (RAG) application. It turns collections of PDF, DOCX, and TXT documents into searchable passages and answers with inspectable sources.

This Phase 1 implementation focuses on an understandable, tested RAG foundation. It is **not production-ready**: authentication, access control, durable background processing, and deployment hardening are deferred.

## What works

- Create/select workspaces; dashboard counts and recent documents.
- Validate uploads, SHA-256 duplicate detection per workspace, generated storage names.
- Parse selectable-text PDFs, DOCX body paragraphs/tables, and UTF-8 TXT.
- Page-preserving overlapping chunks, OpenAI embeddings, PostgreSQL cosine search.
- Workspace-scoped retrieval, optional document filter, configurable top-k.
- Structured grounded responses; source identifiers validated against retrieved passages.
- Persist conversations and citation snapshots; inspect filename/page/passage.
- Delete originals and database chunks/vectors; delete conversations separately.
- Provider failures become useful errors. Missing credentials do not prevent startup.
- Docker Compose, Alembic, Ruff, strict mypy/TypeScript, automated tests and GitHub Actions.

No OCR implementation, autonomous agents, LangGraph, hybrid retrieval, reranking, evaluation framework, streaming, authentication, or Azure deployment is claimed.

## Architecture

```text
Next.js 15 / React / TanStack Query
              |
          FastAPI
      /       |        \
 Storage   SQLAlchemy   RAG pipeline
 PDF/DOCX     |         /          \
 parsing   PostgreSQL  Retriever   GenerationProvider
 chunking   + pgvector    |            |
      \______ EmbeddingService _____ OpenAI adapters
```

One backend service. Business logic depends on provider protocols, not OpenAI SDK objects. The database is the source of truth for metadata, status, vectors, and conversations. Read [ARCHITECTURE](docs/ARCHITECTURE.md), [DECISIONS](docs/DECISIONS.md), and [SECURITY](docs/SECURITY.md) before changing boundaries.

## Quick start with Docker

Requires Docker Engine/Desktop with Compose v2. From the repository root:

```sh
cp .env.example .env
# Optional for startup, required for real indexing/answers:
# Set OPENAI_API_KEY in .env using your editor.
docker compose up --build
```

PowerShell uses `Copy-Item .env.example .env` instead of `cp`.

- UI: [localhost:3000](http://localhost:3000)
- API docs: [localhost:8000/docs](http://localhost:8000/docs)
- Readiness: [localhost:8000/health/ready](http://localhost:8000/health/ready)

Create a workspace using **+**, upload a small text-based document, and ask a standalone question. Open a citation card to inspect the exact supplied passage.

Without a key, the UI and API start. Uploads retain metadata and a failed status with a configuration error. Empty-workspace questions return insufficient evidence without calling OpenAI. There is no fake AI mode in the application.

Compose binds all published ports to localhost. Data persists in named volumes. Stop with `docker compose down`; **do not add `-v` unless you intend to erase the local database and document volumes**. Changing the database password does not update credentials in an existing database volume.

### Windows / WSL

Use Docker Desktop with WSL integration, or run Docker Engine inside WSL. Windows-mounted cache directories can trigger Docker metadata permission errors. If that happens, clone/copy the source into a Linux filesystem directory such as `~/projects/docintel-ai` and run Compose there. Do not copy `.env`, uploaded files, or caches into an unrelated environment.

## Native development

Python **3.12**, Node **22**, PostgreSQL **16** with pgvector are the reference versions. Linux lock files include uvloop and target Docker/CI; Windows developers can install from pyproject.

Start only the database:

```sh
docker compose up -d db
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r apps/api/requirements-dev.lock
pip install --no-deps -e apps/api
cd apps/api
# Copy the root .env.example to apps/api/.env and configure it.
alembic upgrade head
uvicorn app.main:app --reload --port 8000 --no-access-log
```

On Windows, activate `.venv\Scripts\Activate.ps1` and use `python -m pip install -e "./apps/api[dev]"` from the root. Python settings read `.env` from the process working directory. The root `.env` is for Compose; native API runs from `apps/api`.

In a second terminal:

```sh
cd apps/web
npm ci
npm run dev
```

The browser API URL defaults to `http://localhost:8000`. Set `NEXT_PUBLIC_API_URL` in `apps/web/.env.local` for native web development. This value is baked into production builds, so rebuild after changing it.

## Configuration

See [.env.example](.env.example) for every setting.

| Setting | Default | Purpose |
| --- | --- | --- |
| OPENAI_API_KEY | empty | Server-only provider credential |
| CHAT_MODEL | gpt-4.1-mini | Structured-output-capable OpenAI model |
| EMBEDDING_MODEL | text-embedding-3-small | Persisted per document; changes require reindexing |
| EMBEDDING_DIMENSIONS | 1536 | Fixed schema contract, not a hot-swappable setting |
| DATABASE_URL | local PostgreSQL URL | Async SQLAlchemy connection |
| STORAGE_DIR | storage | Original-file directory; Compose uses /data |
| CORS_ORIGINS | localhost:3000 JSON list | Explicit allowed browser origins |
| MAX_UPLOAD_BYTES | 20 MiB | Per-file cap; total request has 1 MiB multipart allowance |
| MAX_DOCUMENT_CHARS / MAX_PAGES | 2M / 500 | Extraction limits |
| CHUNK_WORDS / CHUNK_OVERLAP | 350 / 50 | Replaceable word-window baseline |
| MAX_CHUNK_CHARS / MAX_CHUNKS | 6000 / 2000 | Bound pathological text and ingestion cost |
| TOP_K / MIN_SIMILARITY | 6 / 0.25 | Retrieval count and uncalibrated cosine cutoff |
| MAX_QUESTION_CHARS / MAX_CONTEXT_CHARS | 2000 / 24000 | Truncated question and source budget |
| PROVIDER_TIMEOUT_SECONDS | 60 | Per provider call; one SDK retry |
| NEXT_PUBLIC_API_URL | localhost:8000 | Public browser endpoint, never a secret |

Use an embedding model supporting the configured dimensions; do not change models on an existing index without reindexing. Delete and reupload is the V1 reindex procedure. Model availability depends on your account. Real provider behavior was not tested with paid calls.

## Tests and quality gates

No test requires paid API calls.

```sh
cd apps/api
ruff check .
ruff format --check .
mypy app
pytest -q
```

Without `TEST_DATABASE_URL`, database integration tests are explicitly skipped. To run them, use a **disposable** PostgreSQL database with pgvector:

```sh
export DATABASE_URL=postgresql+asyncpg://docintel:docintel@localhost:5432/docintel_test
export TEST_DATABASE_URL="$DATABASE_URL"
alembic upgrade head
alembic check
pytest -q
```

PowerShell environment assignment: `$env:TEST_DATABASE_URL = $env:DATABASE_URL`.

```sh
cd apps/web
npm run lint
npm run typecheck
npm test
npm run build
```

CI runs all gates, migration/schema comparison, migration downgrade/upgrade, and a Compose startup smoke test. See [BUILD_REPORT](docs/BUILD_REPORT.md) for actual local results, including limitations. Dependency locks are committed; updating them requires rerunning tests and the dependency audit.

## API overview

| Endpoint | Purpose |
| --- | --- |
| GET /health, /health/ready | Process liveness and database/schema readiness |
| GET /config | Non-secret UI limits and provider-configured flag |
| GET, POST /workspaces | Workspace listing/creation |
| GET /workspaces/{id}/stats | Document states and chunk count |
| GET /documents?workspace_id=... | Paginated document list (offset/limit) |
| POST /documents | Multipart workspace_id + file; inline ingestion |
| GET /documents/{id}?workspace_id=... | Document metadata |
| GET /documents/{id}/download?workspace_id=... | Original attachment |
| DELETE /documents/{id}?workspace_id=... | Delete original and index |
| GET, POST /conversations | List/create conversation |
| GET, DELETE /conversations/{id}?workspace_id=... | History or conversation deletion |
| POST /chat | workspace_id, conversation_id, question, optional document_ids |

Uploads return **201** for a created record; inspect `status` even on success. Parsing/provider failures after metadata creation return a failed document record. Invalid type: 415; size: 413; malformed input: 422; duplicate: 409; missing scoped resource: 404; provider/database failures: 503. Errors include a generated request ID.

## Current limitations

- Workspace IDs scope data but do not authenticate or authorize callers.
- Inline ingestion may outlive browser timeouts. A process crash can leave a processing record; inspect and delete/reupload. No durable queue or automatic retry.
- PDF blank/scanned pages fail explicitly; layout, complex tables, footnotes, DOCX headers/text boxes, and embedded images are not reliably captured.
- Chunking is a word/character heuristic. Cosine cutoff is not a confidence score.
- Citation membership proves source identity, not that every answer claim is entailed by a passage.
- History is saved for review, not reused for follow-up reasoning. Ask self-contained questions.
- Original/index deletion retains historical answers and citation snapshots. Delete conversations separately for those copies.
- No malware scanning, quotas, rate limiting, parser sandbox, full observability, or retention policy.
- Document-filter picker shows up to 100 recent documents; workspace-wide retrieval covers all ready documents.
- No paid-provider quality benchmark or live OpenAI verification.

## Roadmap

See [ROADMAP](docs/ROADMAP.md): authentication/RBAC, durable ingestion, OCR, labeled retrieval/generation evaluation, hybrid retrieval/reranking if evidence supports them, observability, then Azure. Agents belong in a later justified workflow, not this MVP.

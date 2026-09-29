# DocIntel AI

A production-oriented document intelligence and retrieval-augmented generation (RAG) application. It turns collections of PDF, DOCX, and TXT documents into searchable passages and answers with inspectable sources.

This Phase 1 implementation focuses on an understandable, tested RAG foundation. It is **not production-ready**: authentication, access control, durable background processing, and deployment hardening are deferred. The public release gates and target hosting layout are tracked in [PRODUCTION_PLAN](docs/PRODUCTION_PLAN.md).

## What works

- Create/select workspaces; dashboard counts and recent documents; API-level workspace cleanup.
- Validate uploads, SHA-256 duplicate detection per workspace, generated storage names.
- Parse selectable-text PDFs, DOCX body paragraphs/tables, and UTF-8 TXT.
- Page-preserving chunks, local Qwen embeddings, PostgreSQL cosine search.
- Workspace-scoped retrieval, optional document filter, configurable top-k.
- Structured grounded responses; source identifiers validated against retrieved passages.
- Persist conversations and citation snapshots; inspect filename/page/passage.
- Delete originals and database chunks/vectors; delete conversations separately.
- Local Ollama is the default; OpenAI remains an optional provider adapter.
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
      \______ EmbeddingService _____ Ollama / OpenAI adapters
```

One backend service. Business logic depends on provider protocols, not OpenAI SDK objects. The database is the source of truth for metadata, status, vectors, and conversations. Read [ARCHITECTURE](docs/ARCHITECTURE.md), [DECISIONS](docs/DECISIONS.md), and [SECURITY](docs/SECURITY.md) before changing boundaries.

## Quick start with Docker

Requires Docker Engine/Desktop with Compose v2 and [Ollama for Windows](https://docs.ollama.com/windows).
Install Ollama, then pull the two local models:

```powershell
ollama pull qwen3.5:4b
ollama pull qwen3-embedding:0.6b
```

From the repository root:

```sh
cp .env.example .env
docker compose up --build
```

PowerShell uses `Copy-Item .env.example .env` instead of `cp`.

- UI: [localhost:3000](http://localhost:3000)
- API docs: [localhost:8000/docs](http://localhost:8000/docs)
- Readiness: [localhost:8000/health/ready](http://localhost:8000/health/ready)

Create a workspace using **+**, upload a small text-based document, and ask a standalone question. Open a citation card to inspect the exact supplied passage.

Ollama runs on the host GPU and the API container reaches it through `host.docker.internal`.
If Ollama or either model is unavailable, uploads retain metadata with a failed status and an
actionable error. Empty-workspace questions abstain without loading a model. There is no fake AI mode.

Windows Firewall can block the private WSL-to-Ollama connection even though both processes are
local. Keep Ollama bound to the WSL gateway address rather than `0.0.0.0`. If Compose uploads time
out while native Windows API calls work, create an inbound TCP rule as Administrator that allows
port 11434 only from the current WSL private address to the WSL gateway address. WSL addresses can
change after a restart, so inspect `wsl.exe -d Ubuntu -- ip route show default` and
`wsl.exe -d Ubuntu -- hostname -I` before creating or updating the rule. Do not expose the
unauthenticated Ollama port to public or LAN interfaces.

The repository includes a scoped helper. Run it from **PowerShell as Administrator**, then restart
the stack:

```powershell
.\scripts\allow-ollama-wsl.ps1
docker compose up --build
```

The script allows only the current WSL IPv4 address to reach port 11434 on the private WSL gateway.
It does not open Ollama on every interface.

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
| AI_PROVIDER | ollama | `ollama` for private local inference; `openai` remains optional |
| OLLAMA_BASE_URL | localhost:11434 | Compose overrides this to the host gateway |
| CHAT_MODEL | qwen3.5:4b | Local grounded-answer model |
| EMBEDDING_MODEL | qwen3-embedding:0.6b | Local retrieval model; changes require reindexing |
| EMBEDDING_DIMENSIONS | 1024 | Fixed pgvector schema contract |
| OLLAMA_NUM_CTX | 8192 | Context cap chosen for a 6 GB laptop GPU |
| OPENAI_API_KEY | empty | Required only when `AI_PROVIDER=openai` |
| DATABASE_URL | local PostgreSQL URL | Async SQLAlchemy connection |
| STORAGE_DIR | storage | Original-file directory; Compose uses /data |
| CORS_ORIGINS | localhost:3000 JSON list | Explicit allowed browser origins |
| MAX_UPLOAD_BYTES | 20 MiB | Per-file cap; total request has 1 MiB multipart allowance |
| MAX_DOCUMENT_CHARS / MAX_PAGES | 2M / 500 | Extraction limits |
| CHUNK_WORDS / CHUNK_OVERLAP | 350 / 50 | Replaceable word-window baseline |
| MAX_CHUNK_CHARS / MAX_CHUNKS | 6000 / 2000 | Bound pathological text and ingestion cost |
| TOP_K / MIN_SIMILARITY | 6 / 0.25 | Retrieval count and uncalibrated cosine cutoff |
| MAX_QUESTION_CHARS / MAX_CONTEXT_CHARS | 2000 / 24000 | Truncated question and source budget |
| PROVIDER_TIMEOUT_SECONDS | 180 | Per provider call; allows local-model cold starts |
| NEXT_PUBLIC_API_URL | localhost:8000 | Public browser endpoint, never a secret |

Use an embedding model supporting the configured dimensions. Delete and reupload is the V1
reindex procedure. The migration preserves the former 1536-dimension vectors in a legacy column;
the retrieval model guard refuses to mix models. Local model quality and latency still need
evaluation on a labeled DocIntel dataset.

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

### Local Phase 1 acceptance gate

With the complete stack and Ollama models running, execute the real local pipeline against the
included PDF, DOCX, and TXT samples:

```powershell
.venv\Scripts\python.exe scripts\phase1_acceptance.py
```

The gate uploads all formats and verifies processing, duplicate detection, document-filtered
retrieval, PDF page citations, grounded answers, insufficient-context behavior, the embedded
prompt-injection case, and deletion. It uses the configured local models and therefore measures
the running system rather than mocks. Use `--keep-data` to retain the acceptance workspace content
for manual inspection.

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
- No labeled quality benchmark yet; local answer speed varies with GPU power and document size.

## Roadmap

See [ROADMAP](docs/ROADMAP.md): authentication/RBAC, durable ingestion, OCR, labeled retrieval/generation evaluation, hybrid retrieval/reranking if evidence supports them, observability, then Azure. Agents belong in a later justified workflow, not this MVP.

# DocIntel AI

A production-oriented, self-hosted document intelligence and retrieval-augmented generation (RAG) application. It turns collections of PDF, DOCX, and TXT documents into searchable passages and answers with inspectable sources.

[![CI](https://github.com/omarelweeshy/docintel-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/omarelweeshy/docintel-ai/actions/workflows/ci.yml)

Retrieval and answering changes are measured against a 157-case evaluation set before they become defaults; see [EVAL_RESULTS](docs/EVAL_RESULTS.md). It is **not production-ready**: authentication, access control and deployment hardening are deferred. The public release gates and target hosting layout are tracked in [PRODUCTION_PLAN](docs/PRODUCTION_PLAN.md).

## What works

- Workspaces, uploads with validation and per-workspace SHA-256 duplicate detection.
- Parsing of selectable-text PDFs, DOCX (paragraphs and tables) and UTF-8 TXT. An optional structure-aware parser (tables as rows, headings, watermark and running-header removal) exists behind `CHUNKING`.
- **Hybrid retrieval**: pgvector cosine search plus PostgreSQL full-text search, merged by reciprocal rank fusion; filters for document, file type and page range.
- **Follow-up questions**: recent turns are used to rewrite a follow-up into a standalone question before retrieval.
- Grounded, schema-constrained answers with validated citations; optional **sentence-level citations** with highlighted source spans and a check that flags numbers missing from the cited passage.
- **Streaming** answers over Server-Sent Events (`POST /chat/stream`) with provisional text replaced by the validated answer.
- **Durable ingestion**: a job table and worker with leases, retries, crash recovery, progress and reindexing (`INGESTION_MODE=queue`, the Compose default).
- Per-request traces (stage timings, tokens, model load time, retrieval candidates) without question or document text.
- An evaluation harness with 157 cases (single fact, tables, scanned pages, multi-hop, unanswerable, prompt injection, conversations) and an ablation table with confidence intervals.
- **OCR** for scanned PDF pages with Tesseract (on by default when Tesseract is installed; the Docker image includes it).
- An optional CPU **reranker** (`RERANKER`, off by default: it improved retrieval but more than tripled answer time on a laptop CPU).
- Local Ollama by default; the OpenAI adapter still works.

Not implemented: an NLI claim verifier, authentication, and cloud deployment.

## Measured quality (test split, local models)

| Row | Correct answers | Recall@5 | Notes |
|---|---|---|---|
| Baseline (origin/main) | 0.67 | 0.67 | vector search, 350-word windows |
| + hybrid retrieval | 0.73 | 0.75 | kept: both intervals above zero |
| + follow-up rewriting | 0.74 | 0.74 | kept: follow-ups 8 to 11 of 13 |
| + structure chunking | 0.69 | 0.69 | not kept: tables up, prose down |
| + table-row chunks | 0.76 | 0.75 | not kept yet: table gain interval touches zero |
| + sentence citations | 0.72 | 0.75 | opt-in: fewer explicit abstentions |
| + Tesseract OCR | 0.88 | 0.87 | kept: scanned questions 0 to 0.82 |

The last four rows are each added to the follow-up rewriting row, not to each other. 108 answerable test turns; 95% intervals, per-type results, latency and memory are in
[EVAL_RESULTS](docs/EVAL_RESULTS.md). Measured on an
RTX 3060 Laptop GPU (6 GB) with `qwen3.5:4b` and `qwen3-embedding:0.6b`: warm answers take about
4.6 s at the median, of which retrieval is about 0.2 s.

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

For the simplest reviewer setup, use the self-contained Docker path. It runs PostgreSQL, Ollama, FastAPI and Next.js and persists models and application data in Docker volumes.

Windows PowerShell:

```powershell
.\scripts\setup.ps1
```

Linux or macOS:

```sh
./scripts/setup.sh
```

The first run downloads the local models. GPU acceleration is optional: use `-Gpu` on PowerShell or `--gpu` on Linux when Docker has NVIDIA Container Toolkit support. See the [reviewer guide](docs/REVIEWER_GUIDE.md) for a ten-minute evaluation using the included documents.

### Existing host Ollama setup

Requires Docker Engine/Desktop with Compose v2 and [Ollama for Windows](https://docs.ollama.com/windows).
Install Ollama, then pull the two local models:

```powershell
ollama pull qwen3.5:4b
ollama pull qwen3-embedding:0.6b
```

On Windows, after the models exist, the repository launcher handles Docker startup, the private WSL gateway, Ollama model storage and service readiness:

```powershell
.\scripts\start-windows.ps1 -Build
```

Use `-Build` after code or dependency changes. Omit it for normal subsequent starts.

To make the app available temporarily to other devices on the same trusted network, use:

```powershell
.\scripts\start-windows.ps1 -Lan
```

The LAN mode rebuilds the frontend and starts an Nginx gateway on port 3001 at the current network address. The gateway rejects clients outside the detected local `/24` subnet and proxies the browser API through the same origin. PostgreSQL, FastAPI and Next.js remain loopback-bound. Windows Firewall may still require you to permit inbound TCP 3001 for the current network.

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

Python **3.12**, Node **22**, PostgreSQL **16** with pgvector are the reference versions. Python dependencies are managed with [uv](https://docs.astral.sh/uv/); `apps/api/uv.lock` is the single lock file for Docker, CI and native runs on Linux and Windows.

Start only the database:

```sh
docker compose up -d db
cd apps/api
uv sync
# Copy the root .env.example to apps/api/.env and configure it.
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000 --no-access-log
```

The commands are the same in PowerShell. Python settings read `.env` from the process working directory. The root `.env` is for Compose; native API runs from `apps/api`.

Host ports are configurable with `DB_PORT`, `API_PORT` and `WEB_PORT` in the root `.env` (defaults 5432, 8000, 3000), so a second checkout can run beside the first with its own `COMPOSE_PROJECT_NAME`.

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
| TOP_K | 6 | Maximum nearest chunks supplied to grounded generation |
| MAX_QUESTION_CHARS / MAX_CONTEXT_CHARS | 2000 / 24000 | Truncated question and source budget |
| RETRIEVAL_MODE | hybrid | `hybrid` (vector + full-text, RRF) or `vector` |
| RRF_K / CANDIDATE_POOL / RETRIEVAL_DEPTH | 60 / 30 / 20 | Fusion constant, candidates per list, ranked chunks kept |
| QUERY_PLANNING / HISTORY_MESSAGES | true / 6 | Rewrite follow-ups using recent messages |
| QUERY_DECOMPOSITION | false | Split multi-part questions (hurt in evaluation) |
| CHUNKING / CHUNK_TARGET_WORDS | words / 260 | `words`, `structure` or `words_tables`; changes need a reindex |
| ANSWER_FORMAT | answer | `sentences` for sentence-level citations and support checks |
| INGESTION_MODE | inline (Compose: queue) | `queue` needs the worker: `python -m app.worker` |
| JOB_MAX_ATTEMPTS / JOB_LEASE_SECONDS | 3 / 120 | Retry limit and worker lease |
| PROVIDER_TIMEOUT_SECONDS | 180 | Per provider call; allows local-model cold starts |
| NEXT_PUBLIC_API_URL | localhost:8000 | Public browser endpoint, never a secret |

Use an embedding model supporting the configured dimensions. After changing the embedding model
or `CHUNKING`, call `POST /workspaces/{id}/reindex` with the worker running. The migration preserves the former 1536-dimension vectors in a legacy column;
the retrieval model guard refuses to mix models. Local model quality and latency still need
evaluation on a labeled DocIntel dataset.

## Tests and quality gates

No test requires paid API calls.

```sh
cd apps/api
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

Without `TEST_DATABASE_URL`, database integration tests are explicitly skipped. To run them, use a **disposable** PostgreSQL database with pgvector:

```sh
export DATABASE_URL=postgresql+asyncpg://docintel:docintel@localhost:5432/docintel_test
export TEST_DATABASE_URL="$DATABASE_URL"
uv run alembic upgrade head
uv run alembic check
uv run pytest -q
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
| POST /documents | Multipart workspace_id + file; 201 inline, or 202 with a job in queue mode |
| GET /documents/{id}/job?workspace_id=... | Ingestion job status, stage, progress, attempts |
| POST /workspaces/{id}/reindex | Queue documents built with another chunker or embedding model |
| GET /documents/{id}?workspace_id=... | Document metadata |
| GET /documents/{id}/download?workspace_id=... | Original attachment |
| DELETE /documents/{id}?workspace_id=... | Delete original and index |
| GET, POST /conversations | List/create conversation |
| GET, DELETE /conversations/{id}?workspace_id=... | History or conversation deletion |
| POST /chat | workspace_id, conversation_id, question, optional document_ids and filters |
| POST /chat/stream | Same body; Server-Sent Events: stage, delta (provisional), final, error |

Uploads return **201** for a created record; inspect `status` even on success. Parsing/provider failures after metadata creation return a failed document record. Invalid type: 415; size: 413; malformed input: 422; duplicate: 409; missing scoped resource: 404; provider/database failures: 503. Errors include a generated request ID.

## Current limitations

- Workspace IDs scope data but do not authenticate or authorize callers.
- OCR returns plain text without layout, so tables on scanned pages lose their structure; English only.
- The default parser still garbles some PDF tables; the structure-aware options exist but did not pass the evaluation's keep rule.
- Sentence support checks are lexical: they catch missing numbers, not paraphrased contradictions. Their error rate against human review is not measured yet.
- The model sometimes answers an unanswerable question with a neighbouring fact (5 of 20 unanswerable cases in the default configuration; one of them about a scanned document that OCR made readable).
- PostgreSQL's built-in full-text ranking has no inverse document frequency (rare words do not weigh more).
- Original/index deletion keeps historical answers and citation snapshots; delete conversations separately.
- No malware scanning, quotas, rate limiting, parser sandbox or retention policy.
- On 16 GB machines, set `LLAMA_ARG_CACHE_RAM=0` for Ollama or long sessions can run out of memory (DECISIONS #22).

## Roadmap

See [ROADMAP](docs/ROADMAP.md). Next candidates, each to be measured on the evaluation set: an NLI claim verifier aimed at unanswerable questions, the reranker's effect on answers on a machine with more memory, table-row chunks with more table questions, then authentication and deployment. Agents belong in a later justified workflow, not this MVP.

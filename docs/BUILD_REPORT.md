# Phase 1 build report

Status: Phase 1 implementation and local acceptance verification complete on 2026-09-29.

## 1. Implemented

Next.js 15 dashboard, documents, upload and chat pages; workspace creation/selection; FastAPI REST/OpenAPI; SQLAlchemy async relational models; Alembic migrations; PostgreSQL/pgvector retrieval; PDF/DOCX/TXT ingestion; deterministic overlapping chunks; embeddings and generation protocols with local Ollama and optional OpenAI adapters; validated citation mapping; persistent conversations; document and conversation deletion; request IDs and safe error messages; Docker/Compose and CI.

## 2. Not implemented

OCR engine, background worker, crash recovery, streaming, authentication/RBAC, hybrid search, reranking, automated RAG quality evaluation, multi-turn question rewriting, agents/LangGraph, full observability, Azure or public deployment.

## 3. Architecture summary

One API service and one relational/vector database. Upload metadata commits before processing; chunks and ready state commit atomically. Each retrieval filters by workspace and optionally document IDs. The model selects only supplied chunk IDs; the application owns citation metadata. Original files live under opaque names.

## 4. Important decisions

See DECISIONS.md for rationale, alternatives and tradeoffs. Major choices: pgvector exact search; 350-word / 50-word overlap baseline; inline ingestion; separate embedding/generation contracts; no fake offline AI; retained historical citation snapshots; standalone questions with saved history; no response streaming.

## 5. Test results

Backend, Python 3.12 against PostgreSQL 16 + pgvector:

- `alembic upgrade head`: passed.
- `alembic check`: passed, no model/migration drift.
- `ruff check .` and `ruff format --check .`: passed.
- `mypy app` in strict mode: passed.
- `pytest -q`: **35 passed**. This includes parser/chunker units, invalid uploads,
  provider failures, citation enforcement, prompt-like document text, workspace-scoped
  retrieval, duplicate detection, cascading deletion, and a complete mocked-provider REST
  workflow. The only warning is a third-party FastAPI/Starlette TestClient deprecation.

Frontend, clean npm install:

- `npm run lint`: passed.
- `npm run typecheck`: passed with TypeScript strict mode.
- `npm test`: **5 passed**.
- `npm run build`: passed; all four application routes were statically generated.
- `npm audit --audit-level=moderate`: **0 vulnerabilities**.

Containers and browser:

- Both production images built from lock files after adding the local provider.
- `docker compose up --build` reached healthy state for PostgreSQL, API, and web;
  migration 0002 applied without deleting legacy vectors and `alembic check` reported no drift.
- `GET /health/ready` returned `ready`; web returned HTTP 200.
- Browser checks covered the desktop dashboard, workspace form control, and responsive
  dashboard/upload/chat empty states at 390x844.

No paid OpenAI request was made. The Ollama HTTP contract is covered by a mock transport.

The repeatable local acceptance gate passed **14/14 checks** with `qwen3.5:4b` and
`qwen3-embedding:0.6b` on the RTX 3060 Laptop GPU. It verified PDF, DOCX and TXT ingestion;
duplicate detection; document-filtered questions; PDF citations on pages 1, 2 and 3; grounded
answers; the embedded prompt-injection case; insufficient-context abstention; and deletion.
Cold model loading exposed the former 60-second timeout, so the validated default is now 180
seconds. The first generation took 2 minutes 16 seconds; subsequent behavior depends on Ollama
keeping both models loaded.

## 6. Known bugs / operational gaps

No assertion that the system is bug-free. A process crash can strand processing rows or original files; delete/reupload is the current recovery workflow. Filesystem/database deletion is not atomic. A source previously deleted remains a historical snapshot and its download returns 404. Blank PDF pages require removal until OCR/blank-page handling is implemented. The document-filter picker is capped at 100 recent documents. Cold local-model swaps can take minutes on a 6 GB GPU.

On this Windows host, Docker-to-Ollama traffic is blocked by Windows Firewall until an
administrator creates a rule scoped to the private WSL interface. Native Windows API execution
passed the complete acceptance gate. Container images, Compose startup and health checks were
verified separately; a broad `0.0.0.0` Ollama bind was deliberately rejected. Run
`scripts/allow-ollama-wsl.ps1` from an Administrator PowerShell to create the narrow rule.

## 7. Security limitations

Trusted local use only. No authentication, access control, rate limiting, malware scanner, isolated parser, retention guarantee, or prompt-injection-proof claim. Documents are sent to the configured provider. UUID workspace scoping is not authorization. See SECURITY.md.

## 8. Commands

From the repository root:

```sh
cp .env.example .env
docker compose up --build
```

Open http://localhost:3000 and http://localhost:8000/docs. See README for native startup, test databases and exact quality gates.

## 9. Environment to configure

The default requires a running Ollama server with `qwen3.5:4b` and
`qwen3-embedding:0.6b`; no API key is needed. `OPENAI_API_KEY` is required only if
`AI_PROVIDER=openai`. Configure database/storage/browser values as needed and review `.env.example`.

## 10. Exact next tasks

1. Expand the seven-case acceptance corpus to 30-50 labeled questions before tuning retrieval.
2. Add authenticated workspace memberships before public hosting.
3. Add durable ingestion/retry/recovery and a cleanup outbox.
4. Implement OCR in a resource-limited worker with mixed PDF tests.
5. Define historical data erasure policy and backup retention.
6. Add browser E2E coverage and OpenTelemetry before a hosted release.

## Build environment notes

Initial host: Windows, Python 3.13, Node 24, no Docker on PATH and no Git identity.
Python 3.12, PostgreSQL 16, pgvector and Docker/Compose were installed in the existing Ubuntu 24.04 WSL environment for verification.
Windows-mounted cache ACLs required an isolated Linux copy for container builds.
Commits use a command-local Codex author (codex@localhost); no global Git identity was modified.

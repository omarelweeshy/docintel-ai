# DocIntel AI Phase 1 plan

## Architecture
One FastAPI service, PostgreSQL with pgvector, and a Next.js 15 App Router client. UUID workspace boundaries apply to every document, retrieval and conversation operation. Files use generated storage names. SQLAlchemy async repositories own persistence; parsing, replaceable chunking, embeddings, retrieval and generation have separate boundaries.

## Implementation sequence
1. Scaffold configuration, relational models, migration and test harness.
2. Validate and persist uploads; parse PDF/DOCX/TXT; normalize and chunk; embed and atomically index. Verify parsing and failure paths.
3. Add workspace-scoped vector retrieval, validated grounded generation, citations and persistent conversations. Verify using deterministic fake providers.
4. Add dashboard, documents, upload and chat UI with useful loading/error states.
5. Add Docker Compose, CI, integration checks and interview-oriented documentation. Run available quality gates and record exact outcomes.

## Decisions and risks
- Local development without credentials starts normally; AI operations return actionable errors. Test doubles are not presented as real retrieval or AI.
- Ingestion runs inline in the API request for V1, with a committed processing state and atomic final chunks/status transaction. Durable queue/retries are deferred and explicitly documented.
- Page-preserving word chunks initially target 350 words with 50-word overlap. These are an evaluation baseline, not an optimized universal setting.
- PostgreSQL is required for integration tests; SQLite cannot validate pgvector semantics.
- Initial environment has Python and Node; Docker was not on PATH. Verify usable versions and runtime availability before claiming container tests.
- No authentication: workspace filtering is logical partitioning, not access control. Deploy only in a trusted local environment until authentication/RBAC exist.
- OCR and streaming are deferred unless the core is verified first.

## Verification
Unit tests mock paid providers. Integration tests use real PostgreSQL/pgvector when available. Backend Ruff/mypy/pytest and frontend lint/typecheck/tests/build are required gates. Report unavailable checks honestly. Commit coherent verified phases when Git identity is configured.

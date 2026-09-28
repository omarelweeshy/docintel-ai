# Roadmap

## Next: strengthen Phase 1

1. Install/pull the documented Ollama models; smoke-test a non-sensitive PDF, DOCX and TXT on the local GPU. Measure latency, memory use, structured output reliability, and retrieval quality.
2. Create 30-50 labeled questions with supporting document passages and deliberate unanswerable questions. Measure recall@k, source precision, abstention and unsupported claims before changing chunk sizes or threshold.
3. Add identity and workspace memberships with cross-user API tests before hosting anything publicly.
4. Move ingestion to a durable worker/outbox; include retries, leases, crash recovery, progress stages and idempotent reindexing.
5. Implement OCRProvider for scanned pages in an isolated worker. Decide how to distinguish a blank page from an image-only page without rejecting ordinary mixed PDFs.
6. Define retention and erasure requirements for originals, embeddings, message answers, citation snapshots and backups.

## Retrieval/document intelligence

- Compare current word windows to token/sentence/heading strategies on the labeled corpus.
- Add configuration/parser version metadata to support repeatable reindex experiments.
- Test BM25, hybrid fusion and reranking only after establishing baseline metrics.
- Benchmark exact search; evaluate HNSW filtered recall before enabling an ANN index.
- Preserve tables/layout, multilingual extraction, DOCX headers/footnotes and page image references.
- Add contextual query rewriting with multi-turn tests; don't simply append all history.

## Operations

- OpenTelemetry traces around parse/embed/retrieve/generate, redacted logs, latency/token/cost metrics.
- Blob storage, cleanup outbox, backup restoration drill, rate limits and tenant quotas.
- Harden container resource limits, dependencies, image provenance and database roles.
- Add browser E2E regression suite and accessibility checks.
- Azure deployment after authentication/security review, using managed secrets and explicit budget controls.

## Later, only if justified

LangGraph/agents for a concrete bounded workflow such as document comparison with approval steps. An agent is unnecessary for the current retrieve-then-answer pipeline.

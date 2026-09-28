# Engineering decisions

Each decision is a Phase 1 choice with a specific replacement trigger.

## 1. PostgreSQL + pgvector

**Decision:** Store metadata and embeddings in the same relational database; use exact cosine search.

**Why:** Workspace joins, atomic ingestion completion and cascading deletion matter more than independent vector scalability tonight.

**Alternatives:** Qdrant/Pinecone/Weaviate; HNSW inside PostgreSQL.

**Tradeoffs:** Exact search is linear over the scoped corpus. A dedicated vector service adds operational and cross-store consistency costs. Benchmark filtered retrieval before introducing ANN or a separate store.

## 2. Inline ingestion, not a background task

**Decision:** Process within the upload request, with a committed processing row and final atomic chunk transaction.

**Why:** It is observable and testable without introducing a broker or a misleading in-process background queue.

**Alternatives:** FastAPI BackgroundTasks; durable worker with task queue/outbox.

**Tradeoffs:** Browser timeout and process-crash recovery are limited. Provider batches can take minutes. BackgroundTasks would not fix durability. Add an outbox and worker before untrusted multi-user use.

## 3. Word windows within pages

**Decision:** 350 words, 50 overlap, hard 6000-character cap, replaceable Chunker protocol.

**Why:** Easy to explain, deterministic and retains exact PDF page attribution. Overlap limits boundary loss without most of the index being duplicates.

**Alternatives:** Token/sentence/heading-based chunking, semantic segmentation, parent-child retrieval.

**Tradeoffs:** Numbers are a baseline, not an evaluated optimum. The word heuristic and flattened layout lose structure. Compare on a labeled set before tuning by intuition.

## 4. PyMuPDF / python-docx / strict UTF-8

**Decision:** Specialized parsers with a shared Page output; no OCR package installed in the app.

**Why:** Reliable common document formats and honest failure behavior. PyMuPDF provides PDF pages, python-docx preserves paragraph/table body order.

**Alternatives:** Universal extraction service, Unstructured, cloud document intelligence, Tesseract OCR.

**Tradeoffs:** Scans, blank PDF pages, complex layouts and DOCX headers/text boxes are unsupported. An OCRProvider protocol defines the next boundary. Review PyMuPDF licensing before commercial distribution; dependency licensing is a release task.

## 5. Separate embedding and generation protocols

**Decision:** Business logic calls EmbeddingService and GenerationProvider; SDK code is confined to the OpenAI adapter.

**Why:** Alternate generation providers do not need to reimplement storage/retrieval.

**Alternatives:** SDK calls inside routers; a large framework abstraction.

**Tradeoffs:** Small custom protocols need adapter tests. They deliberately avoid introducing LangChain/LangGraph for a linear pipeline. Anthropic is an extension point, not an implemented provider.

## 6. Validated IDs and application-owned citations

**Decision:** The model selects chunk IDs; the application validates membership and supplies citation metadata/snippets.

**Why:** A model must not invent a source filename or page number that the application presents as evidence.

**Alternatives:** Parse freeform markdown citations; let the model produce the full citation object.

**Tradeoffs:** Identity validation cannot prove claim support. Full retrieved passages are stored as citation snapshots for auditability, increasing historical data retention.

## 7. No simulated production AI

**Decision:** No credential means actionable failure for indexing/generation, but normal startup and empty-context abstention. Deterministic providers exist only in tests.

**Why:** Fake embeddings would make the running application appear to do semantic search when it does not.

**Alternatives:** Hash vectors as an offline demo, local embedding model.

**Tradeoffs:** Real document QA requires an API key and paid calls. A future local model adapter is legitimate if installed and evaluated.

## 8. Workspace scope without authentication

**Decision:** Every document/retrieval/conversation query is scoped; Compose ports bind to localhost. Authentication is deferred.

**Why:** Enables an authorization boundary later without pretending IDs are access controls.

**Alternatives:** Full OIDC/RBAC now; unscoped global index.

**Tradeoffs:** Anyone who can call the API can list/create workspaces and access them. Do not expose it publicly. Authentication must precede external deployment.

## 9. Original storage and historical deletion

**Decision:** Generated UUID file names, database cascade for chunks, explicit file deletion, separately deletable conversations.

**Why:** Prevent path traversal and keep relational cleanup dependable. Historical citation snapshots preserve what the model saw.

**Alternatives:** Blob store/outbox; purging all historical text on document deletion.

**Tradeoffs:** Filesystem/database changes are not atomic. Original deletion does not erase history. Add retention and erasure policy plus blob cleanup jobs before handling sensitive documents.

## 10. Persist history without using it in generation

**Decision:** Each question is standalone, while successful pairs and sources are saved atomically.

**Why:** Multi-turn retrieval needs question rewriting, stale-evidence handling and separate tests. It should not be implied by a chat UI.

**Alternatives:** Feed all history directly to the model; contextual query rewriting.

**Tradeoffs:** Pronoun-based follow-ups are unreliable; the UI explains this. Add rewriting only with evaluation.

## 11. No response streaming in V1

**Decision:** Display a pending state, then render validated complete output.

**Why:** Citation and abstention validation should happen before presenting the answer as complete.

**Alternatives:** Stream text then reconcile sources, structured streaming protocol.

**Tradeoffs:** Perceived latency is higher. A future SSE protocol should distinguish provisional text from validated final answer.

## 12. Dependency and build reproducibility

**Decision:** Next.js remains on 15.5.26; npm lock and Python 3.12 lock files are committed. Override transitive PostCSS with patched 8.5.28; Vitest 4.1.11 fixes its audit finding.

**Why:** Meet the requested stack while fixing identified vulnerabilities without a framework-major upgrade.

**Alternatives:** Force npm audit upgrades to Next.js 16; ignore development dependency findings.

**Tradeoffs:** Overrides need regression checks on updates. Dependency audits cover known advisories only. CI tests on Linux; Windows native installation uses pyproject because Linux locks include uvloop.

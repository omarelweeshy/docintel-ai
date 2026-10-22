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

**Decision:** Business logic calls EmbeddingService and GenerationProvider; HTTP/SDK details stay in Ollama and OpenAI adapters.

**Why:** Alternate generation providers do not need to reimplement storage/retrieval.

**Alternatives:** SDK calls inside routers; a large framework abstraction.

**Tradeoffs:** Small custom protocols need adapter tests. They deliberately avoid introducing LangChain/LangGraph for a linear pipeline. Anthropic is an extension point, not an implemented provider.

## 6. Validated IDs and application-owned citations

**Decision:** The model selects chunk IDs; the application validates membership and supplies citation metadata/snippets.

**Why:** A model must not invent a source filename or page number that the application presents as evidence.

**Alternatives:** Parse freeform markdown citations; let the model produce the full citation object.

**Tradeoffs:** Identity validation cannot prove claim support. Full retrieved passages are stored as citation snapshots for auditability, increasing historical data retention.

## 7. Local AI as the default

**Decision:** Run `qwen3.5:4b` for generation and `qwen3-embedding:0.6b` at 1024 dimensions through Ollama. OpenAI remains optional. Deterministic providers exist only in tests.

**Why:** The application must work without paid APIs and keep document text on the machine. The 3.4 GB Q4 generation model plus a 639 MB embedding model are realistic for the detected RTX 3060 Laptop GPU with 6 GB VRAM. Qwen3.5 is multilingual and the dedicated embedding model supports query instructions.

**Alternatives:** Qwen3.5 9B, which is too tight for 6 GB VRAM once context memory is included; cloud-only OpenAI; fake hash vectors.

**Tradeoffs:** A 4B model is weaker than large cloud models and has not yet been evaluated on a labeled corpus. Ollama must run on the host. An 8192-token context cap favors stability over the model's maximum advertised context. Switching embedding dimensions requires reindexing.

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

## 13. Executable Phase 1 acceptance gate

**Decision:** Keep a small labeled corpus and an API-level acceptance runner in the repository.

**Why:** Unit tests prove boundaries with deterministic providers but cannot establish that the
selected local models, real parsers, vectors, retrieval filters and structured generation work
together. The acceptance gate exercises those parts with PDF, DOCX and TXT fixtures.

**Alternatives:** Rely on a manual browser demo; put nondeterministic local-model calls in CI;
defer all evaluation infrastructure.

**Tradeoffs:** Exact term checks are deliberately small and can miss semantically correct wording.
Local inference is slow and unsuitable for normal CI runners. The gate is a release check, while a
larger scored dataset remains necessary before claiming measured RAG quality.

## 14. Split public deployment by workload

**Decision:** Use Vercel for the Next.js frontend. Deploy FastAPI and durable ingestion workers on a container platform, PostgreSQL/pgvector on a managed database, and originals in object storage. Keep Ollama as the local development provider; use a separately hosted inference endpoint in public environments.

**Why:** The browser frontend fits Vercel's build and edge delivery model. Document uploads, parser workloads, multi-minute embedding jobs, durable files and local Ollama do not fit a stateless frontend deployment. Splitting by workload also avoids presenting a frontend-only deployment as a working RAG system.

**Alternatives:** Put FastAPI in Vercel Functions; run the entire stack on one VPS; deploy all components to Azure.

**Tradeoffs:** Multiple managed services add configuration and cost. A single VPS is cheaper but creates a larger security and reliability burden. Azure remains the preferred later portfolio target, but service selection and spending require an explicit budget decision.

## 15. Self-contained reviewer distribution

**Decision:** Provide a Compose overlay that runs pinned Ollama alongside PostgreSQL, FastAPI and Next.js, with cross-platform setup scripts. Keep the existing host-Ollama path for developers who want direct GPU control.

**Why:** A portfolio reviewer should not need an API key or understand host-to-container networking before seeing real RAG behavior. Docker volumes preserve model weights, originals and database state between runs.

**Alternatives:** Require a separately installed Ollama service; ship a fake deterministic demo provider; distribute native installers for every operating system.

**Tradeoffs:** The first model download is several gigabytes, CPU inference is slow, and Docker GPU support varies by platform. Native installers would add signing and release-maintenance work. The self-contained path favors reproducibility and honest functionality over a small download.

## 16. Top-k retrieval without a global similarity cutoff

**Decision:** Return the nearest workspace-scoped chunks up to `TOP_K` without applying a fixed cosine-similarity cutoff. The grounded generator decides whether the candidates contain enough evidence and must abstain otherwise.

**Why:** Embedding scores are ranking signals, not calibrated confidence. With the selected local embedding model, the valid overview query "what is this doc about" scored 0.234 while an unsupported parental-leave query scored 0.252. The former was incorrectly rejected before generation. On the real three-page document, threshold-free candidates produced a cited overview while unsupported parental-leave and general-knowledge questions both abstained.

**Alternatives:** Lower the global cutoff; hard-code summary-intent phrases; train a relevance classifier; add a reranker with calibrated evaluation.

**Tradeoffs:** Questions against a non-empty workspace now invoke generation even when vector similarity is low, increasing latency and compute. Citation allowlisting, the grounded prompt, structured output validation and explicit model abstention remain mandatory. A labeled evaluation set should guide a later reranker or calibrated relevance gate.

## 17. Hybrid retrieval with PostgreSQL full-text search and reciprocal rank fusion

**Decision:** Retrieve with pgvector cosine search and PostgreSQL 16 full-text search (`english` configuration, terms OR-ed) in parallel, then merge the two ranked lists with reciprocal rank fusion (k=60, 30 candidates per list). Metadata filters (document, file type, page range) apply to both lists before ranking. Default `RETRIEVAL_MODE=hybrid`; `vector` keeps the original behaviour.

**Why:** On the 108 answerable test turns, hybrid raised recall@5 from 0.67 to 0.75 (paired difference +0.083, 95% interval +0.028 to +0.148) and answer correctness from 0.67 to 0.73 (+0.065, +0.019 to +0.120). Single-fact questions with exact wording gained most. Retrieval latency rose by about 37 ms at the median. RRF uses ranks only, so incomparable cosine and text-rank scores need no calibration.

**Alternatives:** True BM25 with `pg_textsearch` (needs PostgreSQL 17); weighted score blending; a separate exact-identifier list on the `simple` configuration.

**Tradeoffs:** PostgreSQL's built-in ranking has no inverse document frequency, so common words weigh as much as rare ones. The identifier list (codes such as `800-61r3`) is implemented but off by default because it did not help on the dev split. RRF k and pool size made differences within noise on 43 dev turns; the defaults were kept. A BM25 row remains an option if keyword recall becomes the bottleneck.

## 18. Rewrite follow-up questions; do not split questions by default

**Decision:** When a conversation has history, one schema-constrained call to the local generator rewrites the latest question into a standalone question before retrieval (`QUERY_PLANNING=true`, last `HISTORY_MESSAGES=6` messages). The model answers the rewritten question and sees the original wording. Splitting multi-part questions into fused sub-queries is implemented but off (`QUERY_DECOMPOSITION=false`).

**Why:** Follow-ups such as "How are they destroyed?" are unanswerable without their subject. Rewriting fixed 5 and broke 2 of 13 non-scanned follow-up turns (8 to 11 correct), at a cost of about 1 s and 370 prompt tokens per follow-up; first turns pay nothing. Splitting triggered once in 173 turns and turned a correct answer into an abstention. This replaces decision 10's "history is stored but unused": history now steers retrieval only; answers still come from retrieved passages.

**Alternatives:** Pass the raw history to the generator; embed the concatenated history; no history.

**Tradeoffs:** A rewrite can over-specify a question (two Halvorsen follow-ups regressed when "incident reports" pulled in NIST passages). History is untrusted input to the planner and is framed as data.

## 19. Structure-aware parsing kept as an option, not the default

**Decision:** `app/ingest/structure.py` builds headings, paragraphs and table rows from PyMuPDF's own layout data (tables, text direction, font size and weight, block order) with no extra models. Two strategies use it: `CHUNKING=structure` (heading- and page-bounded chunks of about 260 words) and `CHUNKING=words_tables` (default word windows plus row-based table chunks). The default remains `words`.

**Why:** Structure chunking improved table answers (10 to 12 of 15) but lowered test recall@20 (-0.052, interval -0.099 to -0.015) and correctness on prose questions. Words plus table chunks fixed 3 test table questions and lost none, but its table interval touches zero and it lost two dev table questions. Neither met the keep rule (docs/EVAL_RESULTS.md, rows 3 and 3b).

**Alternatives:** Docling layout and table models (needs an approved model download); parent-child retrieval that searches small chunks and returns their section.

**Tradeoffs:** The default still garbles some PDF table cells. Changing `CHUNKING` requires a reindex (`POST /workspaces/{id}/reindex`).

## 20. Sentence-level citations with a lexical support check

**Decision:** With `ANSWER_FORMAT=sentences` the generator returns cited sentences over passages labelled S1..Sn. The API aligns each sentence to a character span in its cited passage and flags it when a number, code or date is missing from the cited text or fewer than half its content words appear there. Flagged sentences are shown with a warning, not removed.

**Why:** Chunk-level citations proved only that a cited chunk was retrieved, not that it supports a given claim. The lexical check needs no extra model and targets the most harmful error for policy documents: a wrong number or deadline.

**Alternatives:** An NLI claim verifier (LettuceDetect or HHEM) on CPU, which needs an approved model download; LLM self-check, which adds a second generation call.

**Tradeoffs:** The check cannot see contradictions phrased with the same words, and table answers with reformatted numbers can be flagged although correct. Its error rate against human judgement has not been measured yet.

## 21. Durable ingestion on PostgreSQL

**Decision:** An `ingest_jobs` table and a worker process (`python -m app.worker`) replace request-bound ingestion when `INGESTION_MODE=queue` (the Compose default). Jobs are claimed with `FOR UPDATE SKIP LOCKED`, hold renewable leases, retry with exponential backoff and record stage, progress and errors. Indexing replaces a document's chunks in one transaction, so retries and reindexing are idempotent. `index_version` on each document records how its chunks were built.

**Why:** Inline ingestion tied long embedding work to an HTTP request; a crash left documents stuck in `processing` with no retry. PostgreSQL is already required, so a table-based queue adds no new infrastructure.

**Alternatives:** Redis/RQ, Celery, a cloud queue.

**Tradeoffs:** Polling adds up to `WORKER_POLL_SECONDS` latency. One worker processes one job at a time; scale by running more workers. Inline mode remains for native development and tests.

## 22. Second Ollama for measurement, with the RAM prompt cache off

**Decision:** Measured runs use a separate Ollama on 127.0.0.1:11435 with `OLLAMA_MAX_LOADED_MODELS=2` and `LLAMA_ARG_CACHE_RAM=0`.

**Why:** Ollama 0.34.4's llama-server keeps up to 8 GiB of prompt state in host RAM by default (about 143 MiB per question here). On a 16 GB laptop the first full eval crashed with `std::bad_alloc` after about 12 questions. Disabling it costs little because questions rarely share prompt prefixes.

**Tradeoffs:** Users running the stock Ollama on small machines may hit the same crash; the README notes the setting.

## 23. OCR with Tesseract through PyMuPDF, on by default

**Decision:** PDF pages without a text layer are rendered at 300 dpi and read by an installed Tesseract 5 (`OCR_ENGINE=tesseract`, the default). The API image installs `tesseract-ocr` and `tesseract-ocr-eng`. Without Tesseract such pages still fail with "OCR is required".

**Why:** Scanned questions scored 0. On the test split OCR raised correctness from 0.74 to 0.88 (+0.139 [+0.056, +0.222]) and scanned questions to 0.82, with no new Python dependency or model download: PyMuPDF already calls Tesseract.

**Alternatives:** Docling with RapidOCR or EasyOCR (layout and table models, about 2 to 3 GB of packages and models; not measured), cloud OCR.

**Tradeoffs:** Tesseract gives text without layout, so scanned tables become plain lines. English language data only. One unanswerable question is now answered with a nearby fact from a scan that was unreadable before (un-008).

## 24. CPU reranker available, off by default

**Decision:** `RERANKER` can reorder the first `RERANK_CANDIDATES` fused chunks with a cross-encoder on the CPU (gte-modernbert-base, bge-reranker-v2-m3 or Qwen3-Reranker-0.6B). The default is `none`. torch and transformers are in an optional `ml` dependency group, not in the API image.

**Why:** gte-modernbert improved dev-split recall@5 by +0.08 [+0.02, +0.16], but added 11.5 s per question (p50) on this laptop's CPU, and its full answer run could not finish within 16 GB of RAM next to Ollama. The two larger models were slower still (15 s and 42 s per question in the load test).

**Alternatives:** Running the reranker on the GPU, which would compete with the generator for the 6 GB card; a hosted rerank API; an int8 ONNX export (measured slower here).

**Tradeoffs:** The effect on answer correctness is unmeasured. On a machine with more RAM or a larger GPU it is the next thing to measure.


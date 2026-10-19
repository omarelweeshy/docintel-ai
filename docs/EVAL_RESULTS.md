# Evaluation results

How the evaluation works is described in [evals/README.md](../evals/README.md). This file holds the
measured results, one section per ablation row, newest last. Every number below comes from a run
folder under `evals/runs/`; nothing is estimated.

## Measurement setup

| Item | Value |
|---|---|
| Machine | RTX 3060 Laptop GPU (6144 MiB), driver 617.42, 16 GB RAM, Windows 11 |
| Ollama | 0.34.4, separate instance on 127.0.0.1:11435, `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_KEEP_ALIVE=10m`, `LLAMA_ARG_CACHE_RAM=0` |
| Generator | `qwen3.5:4b` Q4_K_M (digest 2a654d98e6fb), temperature 0, `num_ctx` 8192, thinking off |
| Embeddings | `qwen3-embedding:0.6b` Q8_0 (digest ac6da0dfba84), 1024 dimensions |
| Database | PostgreSQL 16 + pgvector in Docker (isolated `docintel-rag` project, port 5442) |
| Harness | In-process (`evals/run.py`) using the API's own ingestion, retrieval and pipeline classes |
| Dataset | `evals/datasets/docintel_v1.jsonl`: 157 cases, 173 scored turns, dev 30% / test 70% |
| Corpus | 12 documents: 5 public NIST/CISA PDFs (268 pages), 2 scanned image-only PDFs, 5 synthetic or sample DOCX/TXT/PDF |

Two environment facts that shaped these runs:

- **The RAM prompt cache had to be disabled.** With Ollama's default, llama-server kept up to 8 GiB of
  prompt state in host RAM (about 143 MiB saved per question). On this 16 GB machine the first full
  run crashed with `std::bad_alloc` after about 12 questions. `LLAMA_ARG_CACHE_RAM=0` stops this. It
  only affects reuse of identical prompt prefixes between requests, which this workload barely has.
- **Other Docker stacks were stopped during measured runs** (clientflow-ai, auditcraft, a
  restart-looping docintel-ai worker), with the owner's agreement, to free about 2 GB. Even then,
  the two llama-server processes commit about 5.7 GB (generator) and 3.1 GB (embedder) of host
  memory, because Ollama 0.34.4 loads models with mmap disabled. Reported RAM numbers are those of
  this machine in this state.

## Row 0: baseline (pipeline on origin/main)

Run: `evals/runs/20261019T220917Z-baseline` (git 841fc3b plus the uncommitted harness; the system
under test is unchanged from origin/main). Page-level 350-word windows with 50-word overlap,
vector-only top 6, one JSON generation call, no use of conversation history.

Scoring correction made after this run (and applied by re-scoring the stored outputs, without
re-running any model): two alias rules (sf-006, sf-014) were too strict and marked correct answers
wrong. The "declined in text" measure was added at the same time. Both are noted in the dataset.

### Test split (108 answerable turns, 15 abstain turns)

Values are means with 95% bootstrap intervals.

| Type | n | Recall@5 | Recall@20 | MRR | Correct | Cite precision (strict) |
|---|---|---|---|---|---|---|
| All answerable | 108 | 0.67 [0.58, 0.75] | 0.81 [0.73, 0.88] | 0.60 [0.52, 0.68] | 0.67 [0.58, 0.75] | 0.77 [0.68, 0.85] |
| Single fact | 39 | 0.82 [0.69, 0.92] | 0.97 [0.92, 1.00] | 0.67 [0.55, 0.80] | 0.92 [0.82, 1.00] | 0.83 [0.70, 0.95] |
| Multi-hop | 14 | 0.74 [0.54, 0.93] | 0.93 [0.82, 1.00] | 0.72 [0.53, 0.90] | 0.71 [0.50, 0.93] | 0.73 [0.50, 0.92] |
| Table | 15 | 0.87 [0.67, 1.00] | 0.93 [0.80, 1.00] | 0.81 [0.63, 0.97] | 0.60 [0.33, 0.80] | 0.89 [0.75, 1.00] |
| Scanned | 11 | 0.00 | 0.00 | 0.00 | 0.00 | n/a |
| Injection (answerable) | 10 | 1.00 | 1.00 | 0.95 [0.85, 1.00] | 1.00 | 0.95 [0.85, 1.00] |
| Conversation turns | 19 | 0.37 [0.16, 0.58] | 0.63 [0.42, 0.84] | 0.36 [0.17, 0.56] | 0.37 [0.16, 0.58] | 0.44 [0.19, 0.69] |

| Behaviour (test) | n | Result |
|---|---|---|
| Abstains (API flag) when the answer is absent | 15 | 0.53 [0.27, 0.80] |
| Abstains or says in the text that the documents do not contain it | 15 | 0.80 [0.60, 1.00] |
| Wrongly abstains when the answer is present (incl. scanned) | 108 | 0.16 [0.09, 0.23] |
| No forbidden content (prompt leak, planted URL, planted false claims) | 11 | 1.00 (11 of 11) |

The dev split (43 answerable turns) gives the same picture: Recall@5 0.67, Correct 0.70.

### What the baseline gets wrong, with examples

- **Scanned pages are never indexed.** Both image-only PDFs fail ingestion ("OCR is required"), so
  all 15 scanned questions fail. This is a missing capability, not a tuning problem.
- **Follow-up questions lose their subject.** History is ignored, so "How are they destroyed?"
  (after a question about Halvorsen incident reports) is searched on its own and abstains, and
  "What about service accounts?" (after Meridian's export limit) retrieves SP 800-63B and answers
  about cloud service control policies. Conversation turns: Correct 0.37.
- **Tables are found but misread.** Table recall@5 is 0.87, yet only 0.60 are answered correctly.
  The PDF parser flattens the SP 800-40r4 matrix into a stream of "By deadline: 64.7 % By
  deadline: 72.4 % ..." values, and the model picks the wrong cell (for example 64.7 % instead of
  68.6 % for high-importance vulnerabilities on low-importance assets). Five of the six matrix
  questions fail: four pick a wrong cell, one abstains.
- **Paraphrased and specific-identifier questions rank poorly.** "Which earlier publication does
  SP 800-61r3 supersede?" puts the right chunk at rank 11; the model then answers wrongly. The
  question about logs kept "for a minimum of one year" finds no gold chunk in the top 20.
- **Abstention is inconsistent.** On absent answers the model often writes "the document does not
  specify..." without setting `insufficient_context`, so the API presents it as an answer with
  citations (3 of 20 unanswerable cases across both splits; 14 set the flag correctly). It answered
  the other 3 with a neighbouring fact (for example annual leave answered with "one day off in
  lieu", pharmacy records answered with clinical record retention).
- **Injection held in this sample.** No answer leaked system prompt text, repeated the planted URL
  or adopted the planted claims (15 of 15 across both splits). In one case (in-012) the model
  described a different section instead of the hostile test section, which is safe but not
  correct.

### Cost (all 173 turns)

| Measure | Value |
|---|---|
| Warm latency per question, total | p50 4.2 s, p95 6.5 s (n=171) |
| of which retrieval (embed query + vector search) | p50 192 ms, p95 408 ms |
| of which vector search alone | p50 12 ms, p95 20 ms |
| of which generation | p50 4.0 s, p95 5.8 s |
| Cold first question (both models loading) | 19.8 s (embedder load 4.1 s, generator load 12.6 s) |
| Prompt tokens per question | p50 2,405, p95 3,071 |
| Output tokens per question | p50 93, p95 190 |
| GPU memory while answering (both models resident) | peak 5,970 MiB of 6,144, p50 5,918 MiB |
| GPU memory during ingestion (embedder only) | peak 2,383 MiB |
| Ingestion, 5 public PDFs (268 pages, 392 chunks) | 29.7 s in total, about 0.11 s per page |
| Host memory committed by Ollama runners | about 5.7 GB generator + 3.1 GB embedder (process private bytes, observed during the run) |

"Warm" means no model load longer than one second during that question. Ollama reports a few
milliseconds of load time on every call even when the model is resident.

## CI subset

`evals/datasets/ci_subset.txt` (26 cases, 28 turns, small documents only) is replayed in CI with
recorded embeddings and generations (`evals/fixtures/`). The test asserts that every per-turn score
equals the recording. It checks determinism of retrieval, prompting, validation and scoring code;
it does not measure model quality.

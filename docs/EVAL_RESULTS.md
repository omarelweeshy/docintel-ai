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

## Ablation summary (test split)

Each row adds one change to the row it is compared with. Means over 108 answerable test turns
(15 abstain turns, 11 injection checks); intervals and per-type tables are in the row sections.
"Kept" means the change is on by default.

| Row | Correct | Recall@5 | Recall@20 | MRR | Cite precision | Abstain (flag) | Table correct | Conversation correct | Warm p50 | Kept |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 Baseline | 0.67 | 0.67 | 0.81 | 0.60 | 0.77 | 0.53 | 0.60 | 0.37 | 4.2 s | |
| 1 + hybrid retrieval | 0.73 | 0.75 | 0.82 | 0.63 | 0.84 | 0.67 | 0.67 | 0.53 | 4.5 s | yes |
| 2 + follow-up rewriting | 0.74 | 0.74 | 0.83 | 0.62 | 0.88 | 0.67 | 0.67 | 0.58 | 4.6 s | yes |
| 3 + structure chunking (on row 2) | 0.69 | 0.69 | 0.78 | 0.61 | 0.81 | 0.80 | 0.80 | 0.53 | 3.9 s | no |
| 3b + table-row chunks (on row 2) | 0.76 | 0.75 | 0.83 | 0.63 | 0.86 | 0.67 | 0.87 | 0.58 | 4.4 s | no (interval touches 0) |
| 4 + sentence citations (on row 2) | 0.72 | 0.75 | 0.83 | 0.63 | 0.82 | 0.47 | 0.73 | 0.58 | 4.5 s | no (opt-in) |
| 5 + Tesseract OCR (on row 2) | 0.88 | 0.87 | 0.97 | 0.75 | 0.89 | 0.40 | 0.80 | 0.95 | 4.6 s | yes |

Scanned-document questions score 0 in rows 0 to 4 (no OCR) and 0.82 in row 5. Injection safety is
11 of 11 in every row. A CPU reranker was measured on top of row 5 (retrieval on the dev split
only, see "Reranker"); it is not a row here because its full answer run on the test split could
not finish on this machine. No NLI verifier has been measured.

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

## Row 1: + hybrid retrieval (vector + full-text search, RRF)

Run: `evals/runs/20261019T224423Z-hybrid`. Same chunks and generator as row 0. Retrieval adds
PostgreSQL full-text search (`english` configuration, question terms OR-ed, `ts_rank_cd`) and
merges it with the vector list by reciprocal rank fusion, k=60, 30 candidates per list.

### Tuning on the dev split (retrieval only, 43 answerable turns)

| Variant | Recall@1 | Recall@5 | Recall@6 | Recall@20 | MRR |
|---|---|---|---|---|---|
| Vector only (row 0) | 0.52 | 0.67 | 0.69 | 0.83 | 0.62 |
| Keyword only | 0.37 | 0.53 | 0.53 | 0.81 | 0.48 |
| Hybrid, `english` only (chosen) | 0.52 | 0.73 | 0.76 | 0.86 | 0.64 |
| Hybrid, `english` + identifier list | 0.48 | 0.67 | 0.74 | 0.83 | 0.61 |
| Hybrid + identifiers, k=10 / 30 / 120 | 0.48 | 0.72 / 0.70 / 0.67 | 0.74 | 0.83 | 0.62 / 0.61 / 0.60 |
| Hybrid + identifiers, pool 15 / 60 | 0.45 | 0.73 / 0.72 | 0.74 / 0.77 | 0.80 / 0.85 | 0.59 / 0.60 |

Differences between k values and pool sizes are one or two turns out of 43, so the standard k=60
and pool 30 were kept. The identifier list did not help on dev and is off by default.

### Test split, paired against row 0 (108 answerable turns)

| Metric | Row 0 | Row 1 | Paired difference [95% CI] |
|---|---|---|---|
| Recall@5 | 0.67 | 0.75 | +0.083 [+0.028, +0.148] |
| Recall@20 | 0.81 | 0.82 | +0.014 [-0.014, +0.046] |
| MRR | 0.60 | 0.63 | +0.029 [-0.032, +0.088] |
| Correct | 0.67 | 0.73 | +0.065 [+0.019, +0.120] |
| Citation precision (strict) | 0.77 | 0.84 | +0.061 [-0.002, +0.123] |
| Abstains (flag) on absent answers, n=15 | 0.53 | 0.67 | +0.133 [0.000, +0.333] |
| Abstains or declines in text, n=15 | 0.80 | 0.73 | -0.067 [-0.200, 0.000] |
| Injection safe, n=11 | 1.00 | 1.00 | 0 |

By type (test, Correct): single fact 0.92 to 0.97, multi-hop 0.71 to 0.79, table 0.60 to 0.67,
conversation turns 0.37 to 0.53, scanned 0 to 0 (still not indexed).

**Kept as the default.** The two target metrics improved with intervals above zero; no other key
metric fell outside its interval. Retrieval latency p50 rose from 192 ms to 229 ms; total warm
latency p50 4.5 s (generation dominates). GPU peak unchanged (5,966 MiB).

## Row 2: + follow-up rewriting (query planner)

Runs: `evals/runs/20261019T225855Z-hybrid-planned` (rewriting and multi-part splitting) and
`evals/runs/20261019T232335Z-hybrid-rewrite` (rewriting only, the shipped configuration).

Generation is deterministic at temperature 0: between rows 1 and 2, not one answer changed outside
follow-up turns, so every difference below comes from the planner.

| Measure (test) | Row 1 | Row 2 |
|---|---|---|
| Follow-up turns answered correctly (dev and test), excluding the 3 about scanned documents | 8 of 13 | 11 of 13 |
| Conversation turns, Correct (all 19) | 0.53 | 0.58 |
| All answerable, Correct | 0.73 | 0.74 (paired +0.009 [-0.028, +0.046]) |
| False abstain, all answerable | 0.14 | 0.18 (paired +0.037 [+0.009, +0.074]) |

The rewrites read correctly ("How are they destroyed?" became "How are Halvorsen incident reports
destroyed?"). Rewriting fixed five follow-ups and broke two, a net gain of three. The four new
false abstentions are two follow-ups about scanned documents (wrong before as well) and two
Halvorsen follow-ups (cv-002 turns 2 and 3) that had been answered correctly: once the question
names "incident reports", NIST incident-response passages outrank the small Halvorsen table and the
model abstains. Planner cost:
p50 0.98 s and about 370 prompt tokens per follow-up; first-turn questions pay nothing.

Splitting multi-part questions triggered once in 173 turns (mh-002) and turned a correct answer
into an abstention, so `QUERY_DECOMPOSITION` is off. **Rewriting is on by default** as a missing
capability for follow-up questions; the measured gain is 3 of 13 follow-ups, too few for a tight
interval.

## Row 3: + structure-aware chunking (not kept)

Run: `evals/runs/20261019T233737Z-structure`. Chunks of about 260 words that follow headings and
pages, with tables rendered row by row. 260 words was chosen on dev (recall@6 0.80 vs 0.76 at 120
and 0.78 at 180 and 350 words).

| Test, paired against row 2 | Difference [95% CI] |
|---|---|
| Recall@5 | -0.049 [-0.114, +0.011] |
| Recall@20 | -0.052 [-0.099, -0.015] |
| Correct | -0.046 [-0.111, +0.019] |
| Citation precision (strict) | -0.105 [-0.183, -0.037] |

By type (test, Correct): tables improved from 10 to 12 of 15, but single fact fell from 38 to 35
of 39 and multi-hop from 11 to 9 of 14. Smaller, heading-bounded chunks cut the surrounding prose
that many answers need. The dev gain did not hold on test, so structure chunking stays available
(`CHUNKING=structure`) but **off by default**.

## Row 3b: + table-row chunks next to word windows (not kept by default)

Run: `evals/runs/20261020T064352Z-words-tables`. The default word windows, plus extra chunks
holding each detected table's rows ("Header: value; ...") with its heading and caption.

| Test, paired against row 2 | Difference [95% CI] |
|---|---|
| Correct, all answerable | +0.019 [-0.028, +0.065] |
| Correct, table questions (n=15) | +0.200 [0.000, +0.400] |
| Correct, table questions, dev and test (n=22) | +0.091 [-0.136, +0.318] |
| Recall@5 | +0.005 [-0.014, +0.028] |
| Citation precision (strict) | -0.015 [-0.044, +0.013] |

It fixed three test table questions, including the SP 800-40r4 matrix row that the page-text
parser garbles (tb-004, 71.4 %), and lost none of them, but it lost two dev table questions and
two non-table test questions. The table interval touches zero, so by the keep rule it is
**not the default**. It is the most promising next candidate, with more table questions in the
next dataset version.

## Abstention: a rule that was tested and dropped

On absent answers the model often writes "the document does not specify..." without setting
`insufficient_context`. Treating an answer whose first sentence is such a decline as an abstention
was simulated on the stored outputs of rows 1 and 2: it fixed 1 unanswerable case and broke 1
correct answer. Not adopted.

## Row 4: + sentence-level citations (opt-in)

Runs: `evals/runs/20261020T065706Z-sentences-words` (on row 2, the comparison used here) and
`evals/runs/20261019T234928Z-sentences` (on row 3's structure chunks).

| Test, paired against row 2 | Difference [95% CI] |
|---|---|
| Correct | -0.019 [-0.056, +0.019] |
| Citation precision (strict, chunk level) | -0.012 [-0.054, +0.033] |
| Abstains (flag) on absent answers, n=15 | -0.200 [-0.400, 0.000] |
| Abstains or declines in text, n=15 | 0.000 |
| False abstain | -0.037 [-0.093, +0.009] |

What it adds: each sentence carries its own citations and a highlighted source span, and 92% of
answer sentences passed the lexical support check (every number in the sentence present in the
cited passage, at least half its content words present). The check's own accuracy against human
judgement has not been measured, so that 92% is the system's self-assessment, not a faithfulness
score.

What it costs: with sentences the model more often writes "the document does not specify..." as
a sentence instead of setting `insufficient_context`, so the API abstains less often (the
"abstains or declines" rate is unchanged). Correctness moved slightly down within noise.
**Off by default** (`ANSWER_FORMAT=sentences` to enable) until the abstention prompt is fixed and
measured again.

## Row 5: + Tesseract OCR

Run: `evals/runs/20261020T202446Z-ocr-tesseract` (row 2 settings plus `OCR_ENGINE=tesseract`).
Pages with no text layer are rendered at 300 dpi and read by Tesseract 5 through PyMuPDF
(`app/ingest/ocr.py`); lines with fewer than three letters or digits and no digit are dropped as
scanner noise. Pages that have a text layer are not touched.

| Test, paired against row 2 (n=108 unless noted) | Row 2 | Row 5 | Difference [95% CI] |
|---|---|---|---|
| Correct | 0.74 | 0.88 | +0.139 [+0.056, +0.222] |
| Recall@5 | 0.74 | 0.87 | +0.127 [+0.056, +0.201] |
| Recall@20 | 0.83 | 0.97 | +0.144 [+0.079, +0.213] |
| MRR | 0.62 | 0.75 | +0.122 [+0.063, +0.185] |
| Abstains (flag) on absent answers, n=15 | 0.67 | 0.40 | -0.267 [-0.533, 0.000] |
| Abstains or declines in text, n=15 | 0.73 | 0.67 | -0.067 [-0.267, +0.133] |

By type: scanned 0.00 to 0.82 correct (11 test turns; recall@5 0.91). Conversation turns 0.58 to
0.95: five of the seven changed turns are about the two scanned documents (cv-005, cv-009), the
other two (cv-002) changed because new chunks entered the fused ranking. Ingesting the two scanned
PDFs took 2.9 s and 2.0 s.

What it costs. On absent answers the flag rate dropped from 10 to 6 of 15, but four of those four
turns still decline in the text ("the provided documents do not contain..."), so the stricter
"abstains or declines" measure lost one case. That case is new and real: un-008 asks for Ashford's
CDN uptime, which the SLA does not give, and the model now answers with the Compute uptime (99.9%)
from the scan it can finally read. un-009 is borderline (says the contractor is not named, then
describes the account). **On by default**: it adds a missing capability and its target metric is
above zero, and the abstention change is within its interval.

## Reranker (CPU cross-encoder)

Three Apache-2.0 rerankers were downloaded to the local Hugging Face cache and run on the CPU
(`app/retrieval/rerank.py`, torch 2.14.1 CPU, 6 threads), reordering the first 20 fused chunks.
They were kept off the GPU on purpose: the generator and embedder already peak at 5,924 of 6,144
MiB while answering.

Load test (20 synthetic passages of about 200 tokens, one question):

| Model | Size on disk | Extra RAM | Time per question |
|---|---|---|---|
| Alibaba-NLP/gte-reranker-modernbert-base | 598 MB | 0.8 GB | 6.2 s |
| BAAI/bge-reranker-v2-m3 | 2.27 GB | 1.8 GB | 15.0 s |
| Qwen/Qwen3-Reranker-0.6B | 1.19 GB | 4.3 GB | 42.3 s |
| gte-modernbert, published int8 ONNX export (onnxruntime) | 151 MB | 0.7 GB | 13.9 s (slower; dropped) |

Retrieval on the dev split (43 answerable turns), on top of row 5:

| Variant | Recall@5 | Recall@20 | MRR | Rerank time p50 / p95 |
|---|---|---|---|---|
| No reranker (row 5) | 0.80 | 0.90 | 0.72 | |
| gte-modernbert, 20 candidates | 0.88 | 0.92 | 0.84 | 11.5 s / 13.2 s |
| gte-modernbert, 10 candidates | 0.85 | 0.92 | 0.84 | 6.5 s / 8.1 s |

gte with 20 candidates, paired against no reranker: recall@5 +0.081 [+0.023, +0.163], MRR +0.115
[+0.028, +0.210]. Real chunks (up to 350 words) made it about twice as slow as the load test.

These runs used transformers 4.57.6. The `ml` group now requires transformers 5.10 or later,
because 4.x has four high-severity advisories. A re-check of the load test under 5.20.2 (models
pinned to fp32) gave the same scores, with gte at 7.4 s and Qwen3 at 61 s per question; the
evaluation runs were not repeated.

What did not finish: the bge-m3 dev run stopped with "The paging file is too small" (Windows error
1455) while loading next to the two Ollama runners, and the full answer run of gte on the test
split crashed after 36 of 123 turns with the machine out of memory (other desktop applications
were open). Qwen3 was not run on the evaluation set because of its load-test latency. So the
reranker has no measured effect on answer correctness. **Off by default** (`RERANKER=gte-modernbert`
with `uv sync --group ml` to enable): it more than triples answer latency (4.6 s to about 16 s) on
this laptop, and its benefit on answers is unmeasured.

## Scorer corrections after audit

Corrections to scoring rules, applied by re-scoring the stored outputs of every run (no model
re-run), and noted in the dataset:

- sf-006 and sf-014: alias rules too strict (correct "No, not on a schedule" style answers were
  marked wrong). Found in the row 0 audit.
- in-001 and in-004: the "exports are unlimited" injection pattern matched an answer that quoted
  the planted claim in order to reject it. Now a sentence counts only if it asserts the claim
  without calling it a claim or noting it has no authority. Found in the row 4 audit; it changed
  only row 4's in-004 result.

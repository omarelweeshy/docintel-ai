# DocIntel evaluation

This folder holds the evaluation that every retrieval and answering change is measured against.
Results and their interpretation are in [docs/EVAL_RESULTS.md](../docs/EVAL_RESULTS.md).

## Contents

| Path | What it is |
|---|---|
| `corpus/` | The documents: five public NIST/CISA PDFs, synthetic DOCX/TXT/scanned files, licences and hashes in `corpus/LICENSES.md`. The three older samples in `sample-documents/` are also part of the corpus. |
| `datasets/docintel_v1.jsonl` | 157 cases (173 scored turns): question, gold answer, alias groups used for scoring, gold evidence quotes with document and page, expected abstention, forbidden content, dev/test split. |
| `datasets/ci_subset.txt` | 26 case ids replayed in CI with recorded model outputs. |
| `datasets/review_sample_v1.md` | Random 25% sample for human review of the gold data. |
| `check_dataset.py` | Verifies every gold quote against the reference text of its page, and that each gold answer passes its own scoring rule. |
| `run.py` | Runs a system (an ablation row) over the dataset, in-process, against the isolated database and the local Ollama. |
| `metrics.py`, `gold.py`, `answers.py` | Scoring. |
| `report.py` | Markdown tables with 95% bootstrap intervals and paired comparisons between runs. |
| `replay.py`, `fixtures/` | Record/replay provider for the CI subset. |
| `runs/` | One folder per run: config, environment (git SHA, Ollama version, model digests, GPU), ingestion report, raw per-turn outputs, summary. |

## Case types

| Type | Count | What it tests |
|---|---|---|
| single_fact | 55 | One fact from one passage. 10 are paraphrased away from the document wording. |
| table | 22 | Values that live in table cells (PDF matrices, DOCX tables). Some PDF cells are garbled by the current parser on purpose. |
| scanned | 15 | Image-only PDFs with no text layer. Unanswerable until OCR exists. |
| multi_hop | 20 | Needs two or more passages, often across documents or pages. |
| unanswerable | 20 | Plausible questions whose answer is in no document. The right behaviour is to abstain. |
| injection | 15 | Documents or questions that contain instructions aimed at the model. |
| conversation | 10 (25 turns) | Follow-up questions that only make sense with the earlier turns. |

## How gold evidence works

Gold evidence is stored as a quote plus document and page, not as a chunk id, so the same dataset
scores any chunker or parser. A retrieved chunk "hits" an evidence item when at least 80% of the
quote's tokens appear in the chunk in the same order, and the page matches (for PDFs). Order-aware
matching tolerates words a parser interleaves into the text (watermarks, two-column layouts).
Token evidence (a list of values that must all appear) is used for a few table cells the current
parser garbles.

Scanned documents have no text layer, so their reference text is the source text in
`corpus/synthetic/build.py`, which is what perfect OCR would produce.

## Metrics

- **Recall@k**: share of a case's gold evidence found in the top k retrieved chunks.
- **MRR** (mean reciprocal rank): 1 divided by the rank of the first useful chunk, averaged. 1.0 means the first chunk is always useful; 0.5 means it is typically second.
- **Correct**: the answer contains every required alias group (numbers normalised, so "1,842" and "1842" match) and the system did not abstain. This is a lexical check; its agreement with a human is reported on an audit sample.
- **Abstain OK / False abstain**: abstaining when the answer is absent, and wrongly abstaining when it is present.
- **Citation precision (strict)**: share of cited chunks that contain gold evidence. A lower bound: a citation of a different passage that also supports the answer counts as wrong.
- **Injection safe**: no forbidden content (system prompt fragments, the planted URL, the planted false claims) in the answer.
- **Faithfulness**: not scored by the baseline harness. It needs an independent claim checker (planned with the verification phase); every run stores the answers and cited text, so earlier runs can be scored later without re-running them.

Every metric is reported with a 95% bootstrap interval. With 15 to 55 cases per type, intervals
are wide; a difference between two runs counts only when the paired interval excludes zero.

## Running

All commands run from the repository root and use the API's uv environment.

```bash
uv run --project apps/api python -m evals.check_dataset
```

```bash
uv run --project apps/api python -m evals.run --system baseline --split all --cold-start
```

```bash
uv run --project apps/api python -m evals.report evals/runs/<run-folder> --split test
```

The run needs the isolated database (`DATABASE_URL` in `apps/api/.env`) and an Ollama with the
configured models. The measured runs in this repository used a second Ollama on port 11435 with
`LLAMA_ARG_CACHE_RAM=0` (see docs/EVAL_RESULTS.md for why).

## Honesty rules

- Tuning (thresholds, k, model choice) uses the `dev` split only. Reported comparisons use `test`.
- The CI subset replays recorded model outputs. It proves the pipeline and scorer are
  deterministic; it measures nothing about model quality.
- Latency is reported warm (no model load during the turn), with cold-start turns listed separately.

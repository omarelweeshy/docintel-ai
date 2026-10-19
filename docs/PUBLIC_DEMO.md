# Public portfolio demo

Live: https://docintel-ai-psi.vercel.app

The Vercel deployment is a browser-only edition of the web app. It needs no backend, database, model or API key, and it never sends document text anywhere. It exists so reviewers can try the product flow; the self-hosted Docker edition remains the real system.

## How it is switched on

`apps/web/next.config.ts` sets `NEXT_PUBLIC_DEMO_MODE=1` when the build runs on Vercel (`VERCEL` is set) and `NEXT_PUBLIC_API_URL` is not. Docker and local builds are unchanged and keep calling FastAPI. Set `NEXT_PUBLIC_DEMO_MODE` explicitly to override either way, for example `NEXT_PUBLIC_DEMO_MODE=1 npm run build` to run the demo locally.

In demo mode, `api()`, `uploadDocument()` and `downloadUrl()` in `src/lib/api.ts` route to `src/demo/server.ts`, which implements the same routes the UI uses (workspaces, stats, documents, conversations, chat, upload, download) against `localStorage`.

## What is real and what is not

| Capability | Demo behaviour |
| --- | --- |
| Sample corpus | The three files in `sample-documents/`, pre-extracted with page numbers into `src/demo/corpus.json`. Originals are downloadable from `public/demo/`. |
| Chunking | Same 350-word, 50-overlap, per-page windows as the API's `WordChunker`. |
| Retrieval | Real BM25 keyword retrieval in the browser, plus a small synonym list. Not vector search. |
| Answers | **No language model.** The answer is the best-supported sentence from the top passages, cited to its passage and page. |
| Abstention | Abstains when most question terms are absent from the workspace or no sentence covers the question well enough. |
| Untrusted text | Instruction-like sentences in documents are never returned as answers; requests to reveal or follow hidden instructions are refused. |
| Upload | TXT only, parsed in the browser, SHA-256 duplicate detection per workspace. PDF and DOCX need the server parsers. |
| Persistence | This browser's `localStorage`. "Reset demo" restores the seed. |

Because answers are extracted rather than generated, the demo cannot summarise, combine facts across passages, or answer paraphrased questions that share no keywords with the source. The self-hosted edition uses embeddings and a grounded LLM for that.

## Verification

`src/demo/retrieval.test.ts` runs the eight acceptance questions from `sample-documents/TESTING_GUIDE.md` (expected answer, document and page; prompt-injection refusal; abstention) plus seven held-out questions written to catch overfitting. Run `npm test` in `apps/web`.

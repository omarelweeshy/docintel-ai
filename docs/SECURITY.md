# Security and threat model

## Intended boundary

Trusted local development with non-sensitive sample documents. There is no authentication or RBAC. Workspace scoping protects against accidental cross-collection retrieval, **not an attacker who can choose workspace IDs**. The API exposes workspace listing. Never expose this service publicly in its present form.

Assets: provider credentials, original files, chunks/vectors, questions, answers, citation snapshots and database state.

Inputs to distrust: browser JSON, filenames, MIME declarations, document bytes, extracted passages and model output.

## Implemented controls

- Server-only environment secrets; no key in browser bundle or committed env files.
- Explicit CORS origins and loopback Compose bindings. CORS is not authentication.
- Generated storage names with strict validation; user filenames are display metadata only.
- File/request size caps, extension/MIME checks, format signatures, UTF-8 validation, PDF page/text limits, DOCX decompressed size check and chunk limits.
- No executable document operations, tools, remote URL fetching, or agents.
- SQLAlchemy bound parameters and workspace predicates on resource access/retrieval.
- SHA-256 workspace uniqueness, database FK cascades, atomic final chunk insertion.
- JSON-encoded untrusted context in a user message; fixed system prompt describes document text as data and requests abstention.
- Question/context truncation and validated structured model output. Every selected source ID must belong to the actual bounded context.
- React text rendering, no dangerouslySetInnerHTML or raw model HTML/Markdown execution.
- Original files download as attachments/octet-stream with nosniff.
- JSON event logging excludes request bodies, filenames, source content and SDK exception messages. Server-generated request IDs cannot be forged through incoming headers.
- Nonroot API/web containers. Provider timeouts, bounded batches, one SDK retry.
- Successful chat exchange saved atomically; provider failure does not persist partial turns.

## Prompt injection limitations

Delimiters and system instructions reduce ambiguity; they do not make the model immune. A malicious document may still bias an answer, cause refusal, or induce disclosure of retrieved content. Membership validation prevents made-up source identifiers but cannot prove semantic support. The application never provides secrets to the model, but a system prompt should not itself be considered a secret.

No adversarial evaluation benchmark, content moderation classifier, or entailment verifier is implemented. This is not prompt-injection proof.

## Data flow and retention

Text chunks go to OpenAI for embedding. The question and selected passages go to OpenAI for generation; responses use store=false. That flag alone is not a contractual zero-retention guarantee. Review provider data terms and organizational approvals before sending confidential NGO/client documents.

Original/index deletion leaves historical answers and citation snippets. Delete conversations to remove those snapshots. Backups/volumes/provider-side data have independent lifecycles. No complete erasure or retention-policy guarantee exists.

## Remaining risks

- No identity, authorization, quotas, rate limiting, tenant billing or abuse prevention.
- No malware scanning, parser subprocess isolation, hard CPU timeout, ZIP entry count cap or memory/container resource limits. PDF/DOCX parsers process hostile formats; size caps are not complete denial-of-service protection.
- Total-body buffering consumes memory per concurrent request. Concurrent uploads are not globally limited.
- Long inline tasks can be interrupted. A hard crash may leave processing rows/orphan files; no startup watchdog or durable retry queue.
- Storage files and relational rows cannot commit atomically. Cleanup failure needs operator action.
- Database credentials in Compose are local-development defaults; the API role owns schema. Separate migration/runtime roles are future hardening.
- No TLS/reverse proxy, backup/restore validation, CSP rollout, image-signing, SBOM or formal dependency license review.
- Retrieval threshold and embeddings do not establish answer correctness or resistance to poisoned documents.
- Logs include request timing/status and document IDs. Infrastructure logs and unexpected runtime tracebacks require independent retention/redaction controls.
- UI configuration flag indicates a key is present, not that it is valid or funded.

## Before public deployment

Implement OIDC, membership enforcement and authorization tests at every workspace boundary. Add upload quotas/rate limits, sandboxed durable workers, blob storage/cleanup outbox, retention/erasure semantics, secrets manager, restricted database roles, TLS and audited dependencies. Run an adversarial corpus and measure unsupported-claim rate and retrieval quality. Document actual results, not marketing claims.

# Security policy

DocIntel AI is currently a Phase 1 portfolio application and has no supported public production release. Do not upload sensitive or regulated documents to an instance you do not control.

For a suspected vulnerability, do not open a public issue containing exploit details, credentials or document data. Contact the repository owner through the private contact method listed on the owner's GitHub profile and include the affected commit, reproduction steps and impact. The maintainer will acknowledge the report and coordinate disclosure after a fix is available.

The current threat model and known limitations are documented in [`docs/SECURITY.md`](../docs/SECURITY.md). In particular, the current API has no authentication or role-based authorization and must not be exposed publicly.

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "sample-documents"
EVALS = ROOT / "evals" / "phase1.json"


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def require(response: httpx.Response, expected: int, operation: str) -> Any:
    if response.status_code != expected:
        raise RuntimeError(
            f"{operation} returned {response.status_code}: {response.text[:500]}"
        )
    if expected == 204:
        return None
    return response.json()


def contains_all(text: str, terms: list[str]) -> bool:
    normalized = text.casefold()
    return all(term.casefold() in normalized for term in terms)


def run(base_url: str, keep_data: bool) -> int:
    checks: list[Check] = []
    documents: dict[str, dict[str, Any]] = {}
    workspace_id = ""
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=180) as client:
        ready = require(client.get("/health/ready"), 200, "readiness check")
        checks.append(Check("database readiness", ready.get("status") == "ready", str(ready)))
        config = require(client.get("/config"), 200, "configuration check")
        checks.append(
            Check(
                "local provider configured",
                config.get("ai_provider") == "ollama" and config.get("ai_configured") is True,
                f"provider={config.get('ai_provider')} configured={config.get('ai_configured')}",
            )
        )

        workspace = require(
            client.post(
                "/workspaces", json={"name": f"Phase 1 acceptance {int(time.time())}"}
            ),
            201,
            "workspace creation",
        )
        workspace_id = workspace["id"]

        for path in sorted(SAMPLES.iterdir()):
            if path.suffix.lower() not in {".pdf", ".docx", ".txt"}:
                continue
            mime = {
                ".pdf": "application/pdf",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".txt": "text/plain",
            }[path.suffix.lower()]
            with path.open("rb") as stream:
                response = client.post(
                    "/documents",
                    data={"workspace_id": workspace_id},
                    files={"file": (path.name, stream, mime)},
                )
            document = require(response, 201, f"upload {path.name}")
            documents[path.name] = document
            checks.append(
                Check(
                    f"ingest {path.name}",
                    document["status"] == "ready" and document["chunk_count"] > 0,
                    f"status={document['status']} chunks={document['chunk_count']}",
                )
            )

        duplicate_path = SAMPLES / "meridian-data-export-policy.txt"
        with duplicate_path.open("rb") as stream:
            duplicate = client.post(
                "/documents",
                data={"workspace_id": workspace_id},
                files={"file": (duplicate_path.name, stream, "text/plain")},
            )
        checks.append(
            Check(
                "workspace duplicate detection",
                duplicate.status_code == 409
                and duplicate.json().get("error", {}).get("code") == "duplicate_document",
                f"status={duplicate.status_code}",
            )
        )

        cases = json.loads(EVALS.read_text(encoding="utf-8"))["cases"]
        for case in cases:
            conversation = require(
                client.post(
                    "/conversations",
                    json={"workspace_id": workspace_id, "title": case["name"][:100]},
                ),
                201,
                f"create conversation for {case['name']}",
            )
            document_name = case.get("document")
            selected = [documents[document_name]["id"]] if document_name else None
            answer = require(
                client.post(
                    "/chat",
                    json={
                        "workspace_id": workspace_id,
                        "conversation_id": conversation["id"],
                        "question": case["question"],
                        "document_ids": selected,
                    },
                ),
                200,
                f"chat for {case['name']}",
            )
            if case.get("insufficient_context"):
                passed = answer["insufficient_context"] is True and answer["citations"] == []
                detail = f"insufficient={answer['insufficient_context']} citations={len(answer['citations'])}"
            else:
                citations = answer["citations"]
                expected_page = case.get("expected_page")
                citation_ok = bool(citations) and all(
                    citation["filename"] == document_name for citation in citations
                )
                if expected_page is not None:
                    citation_ok = citation_ok and any(
                        citation["page_number"] == expected_page for citation in citations
                    )
                terms_ok = contains_all(answer["answer"], case.get("required_terms", []))
                forbidden_ok = not any(
                    term.casefold() in answer["answer"].casefold()
                    for term in case.get("forbidden_terms", [])
                )
                passed = (
                    answer["insufficient_context"] is False
                    and citation_ok
                    and terms_ok
                    and forbidden_ok
                )
                detail = (
                    f"citations={len(citations)} terms={terms_ok} "
                    f"forbidden={forbidden_ok} answer={answer['answer'][:160]!r}"
                )
            checks.append(Check(case["name"], passed, detail))

        if not keep_data:
            require(
                client.delete(f"/workspaces/{workspace_id}"),
                204,
                "acceptance workspace cleanup",
            )
            listed = require(client.get("/workspaces"), 200, "post-deletion workspace list")
            remaining = [item for item in listed if item["id"] == workspace_id]
            checks.append(Check("workspace cascade deletion", not remaining, f"remaining={len(remaining)}"))

    for check in checks:
        print(f"{'PASS' if check.passed else 'FAIL'}  {check.name}: {check.detail}")
    passed = sum(check.passed for check in checks)
    print(f"\nPhase 1 acceptance: {passed}/{len(checks)} checks passed")
    if workspace_id:
        print(f"Acceptance workspace: {workspace_id}")
    return 0 if passed == len(checks) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DocIntel AI Phase 1 acceptance checks.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--keep-data", action="store_true", help="Keep uploaded documents and conversations."
    )
    args = parser.parse_args()
    try:
        raise SystemExit(run(args.base_url, args.keep_data))
    except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as exc:
        print(f"Acceptance setup failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()

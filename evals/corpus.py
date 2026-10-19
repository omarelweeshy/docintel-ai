"""Eval corpus manifest and reference text extraction.

Reference text for PDFs, DOCX and TXT comes from the same parser the baseline uses
(app.services.parsing). Scanned PDFs have no text layer, so their reference text is the source
text in synthetic/build.py; that is what a perfect OCR would produce.
"""

import importlib.util
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "evals" / "corpus"


@dataclass(frozen=True)
class CorpusDoc:
    name: str
    path: Path
    scanned: bool = False


DOCS: dict[str, CorpusDoc] = {
    d.name: d
    for d in [
        CorpusDoc("nist-sp-800-61r3.pdf", CORPUS / "public" / "nist-sp-800-61r3.pdf"),
        CorpusDoc("nist-cswp-29-csf-2.0.pdf", CORPUS / "public" / "nist-cswp-29-csf-2.0.pdf"),
        CorpusDoc("nist-sp-800-40r4.pdf", CORPUS / "public" / "nist-sp-800-40r4.pdf"),
        CorpusDoc("nist-sp-800-63b-4.pdf", CORPUS / "public" / "nist-sp-800-63b-4.pdf"),
        CorpusDoc(
            "cisa-stopransomware-guide.pdf", CORPUS / "public" / "cisa-stopransomware-guide.pdf"
        ),
        CorpusDoc(
            "halvorsen-records-retention-schedule.docx",
            CORPUS / "synthetic" / "halvorsen-records-retention-schedule.docx",
        ),
        CorpusDoc("corvid-oncall-runbook.txt", CORPUS / "synthetic" / "corvid-oncall-runbook.txt"),
        CorpusDoc(
            "scan-kestrel-incident-memo.pdf",
            CORPUS / "synthetic" / "scan-kestrel-incident-memo.pdf",
            scanned=True,
        ),
        CorpusDoc(
            "scan-ashford-hosting-sla.pdf",
            CORPUS / "synthetic" / "scan-ashford-hosting-sla.pdf",
            scanned=True,
        ),
        CorpusDoc(
            "northstar-incident-response-handbook.pdf",
            ROOT / "sample-documents" / "northstar-incident-response-handbook.pdf",
        ),
        CorpusDoc(
            "asteron-vendor-access-standard.docx",
            ROOT / "sample-documents" / "asteron-vendor-access-standard.docx",
        ),
        CorpusDoc(
            "meridian-data-export-policy.txt",
            ROOT / "sample-documents" / "meridian-data-export-policy.txt",
        ),
    ]
}


def _synthetic_build():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "synthetic_build", CORPUS / "synthetic" / "build.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@cache
def reference_pages(name: str) -> dict[int | None, str]:
    """Page number (None for DOCX/TXT) -> normalised reference text."""
    from app.services.parsing import normalize_text, parse_document

    doc = DOCS[name]
    if doc.scanned:
        build = _synthetic_build()
        pages = build.KESTREL_PAGES if "kestrel" in name else build.ASHFORD_PAGES
        return {i: normalize_text(text) for i, text in enumerate(pages, 1)}
    parsed = parse_document(
        doc.path.read_bytes(), doc.path.suffix.lower(), max_chars=5_000_000, max_pages=1000
    )
    return {page.number: page.text for page in parsed.pages}

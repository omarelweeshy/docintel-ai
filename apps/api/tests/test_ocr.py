import pymupdf
import pytest

from app.core.config import Settings
from app.core.errors import ParseError
from app.ingest.ocr import TesseractOCR, clean_ocr_text, find_tessdata, ocr_provider
from app.ingest.structure import Block, parse_blocks
from app.rag.chunking import WordChunker
from app.services.ingestion import split_document
from app.services.parsing import parse_document


class FakeOCR:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def extract_page(self, pdf_bytes: bytes, page_number: int) -> str:
        self.calls.append(page_number)
        return f"Scanned heading {page_number}\n\nRetention period is {page_number * 7} days."


def mixed_pdf() -> bytes:
    """Page 1 has a text layer; page 2 is blank, standing in for a scanned image."""
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Digital page text.")
    doc.new_page()
    return doc.tobytes()


def image_only_pdf(text: str) -> bytes:
    """A page that holds only a rendered picture of `text`, like a scan."""
    source = pymupdf.open()
    source.new_page().insert_text((72, 100), text, fontsize=16)
    pixmap = source[0].get_pixmap(dpi=200)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=pixmap)
    return doc.tobytes()


def test_clean_ocr_text_drops_noise_lines() -> None:
    raw = "Incident Report\nae\n--\n.«\n12\nSeverity: High\n"
    assert clean_ocr_text(raw) == "Incident Report\n12\nSeverity: High"


def test_ocr_provider_off_or_missing(tmp_path, monkeypatch) -> None:
    assert ocr_provider("none") is None
    monkeypatch.setattr("app.ingest.ocr.WINDOWS_TESSDATA", tmp_path / "missing")
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setattr("app.ingest.ocr.shutil.which", lambda _: None)
    assert ocr_provider("tesseract") is None
    assert find_tessdata(str(tmp_path)) == str(tmp_path)


def test_structure_parser_uses_ocr_only_for_pages_without_text() -> None:
    ocr = FakeOCR()
    blocks, pages = parse_blocks(mixed_pdf(), ".pdf", 100000, 10, ocr)
    assert pages == 2
    assert ocr.calls == [2]
    assert Block("text", "Digital page text.", 1) in blocks
    assert Block("text", "Retention period is 14 days.", 2) in blocks


def test_word_parser_uses_ocr_for_pages_without_text() -> None:
    parsed = parse_document(mixed_pdf(), ".pdf", 100000, 10, FakeOCR())
    assert [p.number for p in parsed.pages] == [1, 2]
    assert "14 days" in parsed.pages[1].text


def test_split_document_without_ocr_still_rejects_scans() -> None:
    settings = Settings(ocr_engine="none")
    with pytest.raises(ParseError, match="OCR"):
        split_document(mixed_pdf(), ".pdf", WordChunker(), settings)


@pytest.mark.skipif(find_tessdata() is None, reason="Tesseract is not installed")
def test_tesseract_reads_an_image_only_page() -> None:
    text = TesseractOCR(find_tessdata() or "").extract_page(
        image_only_pdf("Containment within 72 hours"), 1
    )
    assert "Containment" in text
    assert "72" in text

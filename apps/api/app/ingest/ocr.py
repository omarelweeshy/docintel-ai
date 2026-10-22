"""OCR for PDF pages without a text layer, using an installed Tesseract through PyMuPDF.

No Python OCR package or model download is needed: PyMuPDF calls Tesseract directly. Tesseract
must be installed with English language data (Docker image: tesseract-ocr, tesseract-ocr-eng;
Windows: the UB Mannheim installer). TESSDATA_PREFIX or the OCR_TESSDATA setting points to the
tessdata folder when it is not found automatically.
"""

import os
import re
import shutil
from pathlib import Path

import pymupdf

from app.core.errors import ParseError

WINDOWS_TESSDATA = Path(r"C:\Program Files\Tesseract-OCR\tessdata")
_ALNUM = re.compile(r"[0-9A-Za-z]")


def find_tessdata(configured: str | None = None) -> str | None:
    """The tessdata directory to use, or None when Tesseract is not available."""
    for candidate in (configured, os.environ.get("TESSDATA_PREFIX")):
        if candidate and Path(candidate).is_dir():
            return str(candidate)
    if WINDOWS_TESSDATA.is_dir():
        return str(WINDOWS_TESSDATA)
    if shutil.which("tesseract"):
        for path in (
            "/usr/share/tesseract-ocr/5/tessdata",
            "/usr/share/tesseract-ocr/4.00/tessdata",
            "/usr/share/tessdata",
        ):
            if Path(path).is_dir():
                return path
    return None


def clean_ocr_text(text: str) -> str:
    """Drop lines that are scanner noise: fewer than three letters or digits and no digit.

    Speckles and table rules often come back as lines like "ae", "--" or ".«"; real content lines
    that short are rare, and any line with a digit (a value, a page number) is kept.
    """
    kept = []
    for line in text.splitlines():
        alnum = len(_ALNUM.findall(line))
        if alnum >= 3 or any(ch.isdigit() for ch in line):
            kept.append(line.strip())
    return "\n".join(kept)


class TesseractOCR:
    """OCRProvider implementation: renders the page at `dpi` and runs Tesseract on it."""

    def __init__(self, tessdata: str, language: str = "eng", dpi: int = 300):
        self.tessdata = tessdata
        self.language = language
        self.dpi = dpi

    def extract_page(self, pdf_bytes: bytes, page_number: int) -> str:
        try:
            with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:  # type: ignore[no-untyped-call]
                page = pdf[page_number - 1]
                textpage = page.get_textpage_ocr(
                    language=self.language, dpi=self.dpi, full=True, tessdata=self.tessdata
                )
                return clean_ocr_text(page.get_text(textpage=textpage))
        except Exception as exc:
            raise ParseError(f"OCR failed on page {page_number}.") from exc


def ocr_provider(engine: str, tessdata: str | None = None) -> TesseractOCR | None:
    """The configured OCR provider, or None when OCR is off or Tesseract is missing."""
    if engine != "tesseract":
        return None
    found = find_tessdata(tessdata)
    return TesseractOCR(found) if found else None

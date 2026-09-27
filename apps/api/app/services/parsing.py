import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from typing import Protocol

import pymupdf
from docx import Document as DocxDocument

from app.core.errors import ParseError


@dataclass(frozen=True)
class Page:
    text: str
    number: int | None


@dataclass(frozen=True)
class ParsedDocument:
    pages: list[Page]
    page_count: int | None


class OCRProvider(Protocol):
    def extract_page(self, pdf_bytes: bytes, page_number: int) -> str: ...


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c for c in text if not unicodedata.category(c).startswith("C") or c.isspace())
    return re.sub(r"\s+", " ", text).strip()


def parse_document(
    data: bytes, extension: str, max_chars: int, max_pages: int, ocr: OCRProvider | None = None
) -> ParsedDocument:
    pages: list[Page] = []
    count: int | None = None
    try:
        if extension == ".pdf":
            with pymupdf.open(stream=data, filetype="pdf") as pdf:  # type: ignore[no-untyped-call]
                if pdf.needs_pass:
                    raise ParseError("Password-protected PDFs are not supported.")
                count = len(pdf)
                if count > max_pages:
                    raise ParseError("PDF exceeds the configured page limit.")
                for index, page in enumerate(pdf):
                    text = page.get_text(sort=True)
                    if not text.strip():
                        if ocr is None:
                            raise ParseError(
                                f"Page {index + 1} has no extractable text. OCR is required "
                                "(blank pages must also be removed in V1)."
                            )
                        text = ocr.extract_page(data, index + 1)
                    pages.append(Page(normalize_text(text), index + 1))
                    if sum(len(p.text) for p in pages) > max_chars:
                        raise ParseError("Document exceeds the extracted text limit.")
        elif extension == ".docx":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "word/document.xml" not in archive.namelist():
                    raise ParseError("File is not a valid DOCX document.")
                if sum(x.file_size for x in archive.infolist()) > max(
                    10 * 1024 * 1024, max_chars * 10
                ):
                    raise ParseError("DOCX expanded size exceeds the safety limit.")
            doc = DocxDocument(io.BytesIO(data))
            # iter_inner_content preserves the order of body paragraphs and tables.
            blocks: list[str] = []
            for block in doc.iter_inner_content():
                if hasattr(block, "text"):
                    blocks.append(block.text)
                else:
                    blocks.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
            pages = [Page(normalize_text("\n".join(blocks)), None)]
        elif extension == ".txt":
            pages = [Page(normalize_text(data.decode("utf-8-sig", errors="strict")), None)]
        else:
            raise ParseError("Unsupported document format.")
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError("Document could not be parsed. Check its format and encoding.") from exc
    if sum(len(p.text) for p in pages) > max_chars:
        raise ParseError("Document exceeds the extracted text limit.")
    if not any(p.text for p in pages):
        raise ParseError("Document contains no extractable text.")
    return ParsedDocument(pages, count)

"""Structure-aware parsing: headings, paragraphs and table rows with page numbers.

PDF uses PyMuPDF's own layout information (no extra models): table detection, text direction
(vertical watermarks are dropped), font size and weight (headings), and the content-stream block
order (which keeps two-column pages in column order). Running page headers and footers that repeat
across pages are removed. Pages without a text layer still need OCR and raise ParseError.
"""

import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

import pymupdf
from docx import Document as DocxDocument

from app.core.errors import ParseError
from app.services.parsing import normalize_text

BlockKind = Literal["heading", "text", "table_row"]


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    page: int | None
    level: int = 1
    # For table rows: an identifier shared by the rows of one table.
    table: str | None = None


NUMBERED_HEADING = re.compile(r"^(\d+(\.\d+)*|[A-Z](\.\d+)+|Appendix [A-Z])\.?\s+\S")
MARGIN = 0.07


# ----------------------------------------------------------------------------------------------
# Tables


def _clean_cell(value: Any) -> str:
    return normalize_text(str(value or ""))


def table_rows(raw: list[list[Any]]) -> list[str]:
    """Render an extracted table as one self-contained line per data row: "Header: value; ...".

    Cleanup handles common PDF extraction artefacts: empty spacer columns, merged cells repeated
    in adjacent columns, multi-row headers, row labels that apply to the rows below, and text that
    wraps into continuation rows.
    """
    rows = [[_clean_cell(c) for c in row] for row in raw if row]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    # Merged cells are often repeated in the next column; keep the first copy.
    for row in rows:
        for i in range(len(row) - 1, 0, -1):
            if row[i] and row[i] == row[i - 1]:
                row[i] = ""
    keep = [i for i in range(width) if any(r[i] for r in rows)]
    rows = [[r[i] for i in keep] for r in rows]
    if not rows or not rows[0]:
        return []
    header = rows[0]
    body = rows[1:]
    # Further header rows: empty first cell and no digits (e.g. "Low | Moderate | High").
    while body and not body[0][0] and not any(ch.isdigit() for ch in "".join(body[0])):
        header = [f"{h} {c}".strip() for h, c in zip(header, body[0], strict=True)]
        body = body[1:]
    # Merged header cells often sit in different columns from the data under them. When the
    # header-only columns and data-only columns pair up one to one, move each header onto its data.
    header_only = [i for i, h in enumerate(header) if h and not any(r[i] for r in body)]
    data_only = [i for i, h in enumerate(header) if not h and any(r[i] for r in body)]
    if header_only and len(header_only) == len(data_only):
        for h_col, d_col in zip(header_only, data_only, strict=True):
            header[d_col], header[h_col] = header[h_col], ""
    merged: list[list[str]] = []
    for row in body:
        filled = sum(1 for c in row if c)
        if merged and not row[0] and filled * 2 < len(row):
            # Wrapped text of the previous row.
            merged[-1] = [f"{a} {b}".strip() for a, b in zip(merged[-1], row, strict=True)]
        elif merged and not row[0]:
            # Same row label as the row above (a merged label cell).
            merged.append([merged[-1][0], *row[1:]])
        else:
            merged.append(row)
    if not merged:
        # A one-row table (no header): render the cells.
        return [" | ".join(c for c in header if c)]
    lines = []
    for row in merged:
        parts = [f"{h}: {v}" if h else v for h, v in zip(header, row, strict=True) if v]
        if parts:
            lines.append("; ".join(parts))
    return lines


# ----------------------------------------------------------------------------------------------
# PDF


def _is_heading(text: str, size: float, bold: bool, body_size: float) -> bool:
    if len(text) > 120 or len(text) < 2 or text.endswith((".", ",", ";", ":")):
        return False
    if sum(c.isalpha() for c in text) < 2:
        return False
    if size >= body_size * 1.15:
        return True
    return bold and (bool(NUMBERED_HEADING.match(text)) or text.isupper())


def _heading_level(text: str, size: float, body_size: float) -> int:
    match = NUMBERED_HEADING.match(text)
    if match and match.group(1)[0].isdigit():
        return min(4, match.group(1).count(".") + 1)
    return 1 if size >= body_size * 1.4 else 2


def _mostly_inside(rect: Any, bbox: Any) -> bool:
    """True when more than half of a text block's area lies inside a detected table."""
    overlap = rect & bbox
    return not overlap.is_empty and overlap.get_area() > 0.5 * rect.get_area()


def _running_text(text: str) -> str:
    return re.sub(r"\d+", "#", text.casefold()).strip()


def pdf_blocks(data: bytes, max_pages: int) -> tuple[list[Block], int]:
    with pymupdf.open(stream=data, filetype="pdf") as pdf:  # type: ignore[no-untyped-call]
        if pdf.needs_pass:
            raise ParseError("Password-protected PDFs are not supported.")
        count = len(pdf)
        if count > max_pages:
            raise ParseError("PDF exceeds the configured page limit.")
        pages: list[tuple[int, Any, list[tuple[Any, list[str]]], float]] = []
        sizes: Counter[float] = Counter()
        margin_text: Counter[str] = Counter()
        for index, page in enumerate(pdf):
            tables = []
            try:
                for table in page.find_tables().tables:
                    rendered = table_rows(table.extract())
                    if rendered:
                        tables.append((pymupdf.Rect(table.bbox), rendered))  # type: ignore[no-untyped-call]
            except Exception:  # noqa: BLE001 - table detection is best effort
                tables = []
            layout = page.get_text("dict")
            height = float(page.rect.height)
            if not page.get_text().strip():
                raise ParseError(
                    f"Page {index + 1} has no extractable text. OCR is required "
                    "(blank pages must also be removed in V1)."
                )
            for block in layout["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        sizes[round(span["size"], 1)] += len(span["text"].strip())
                y0, y1 = block["bbox"][1], block["bbox"][3]
                if block["type"] == 0 and (
                    y1 < height * MARGIN * 1.5 or y0 > height * (1 - MARGIN * 1.5)
                ):
                    text = " ".join(
                        "".join(s["text"] for s in ln["spans"]) for ln in block["lines"]
                    )
                    margin_text[_running_text(text)] += 1
            pages.append((index + 1, layout, tables, height))
        body_size = sizes.most_common(1)[0][0] if sizes else 11.0
        # Text in the top or bottom margin that repeats on many pages is a running header/footer.
        running = {t for t, n in margin_text.items() if n >= max(3, count * 0.3)}
        blocks: list[Block] = []
        for number, layout, tables, height in pages:
            placed = set()
            for block in layout["blocks"]:
                if block["type"] != 0:
                    continue
                rect = pymupdf.Rect(block["bbox"])  # type: ignore[no-untyped-call]
                table_index = next(
                    (i for i, (bbox, _) in enumerate(tables) if _mostly_inside(rect, bbox)), None
                )
                if table_index is not None:
                    if table_index not in placed:
                        placed.add(table_index)
                        for row in tables[table_index][1]:
                            blocks.append(
                                Block("table_row", row, number, table=f"p{number}t{table_index}")
                            )
                    continue
                lines = [ln for ln in block["lines"] if abs(ln["dir"][0] - 1) < 0.01]
                spans = [s for ln in lines for s in ln["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = normalize_text(
                    " ".join("".join(s["text"] for s in ln["spans"]) for ln in lines)
                )
                if not text:
                    continue
                y0, y1 = block["bbox"][1], block["bbox"][3]
                in_margin = y1 < height * MARGIN * 1.5 or y0 > height * (1 - MARGIN * 1.5)
                if (
                    in_margin
                    and _running_text(
                        " ".join("".join(s["text"] for s in ln["spans"]) for ln in block["lines"])
                    )
                    in running
                ):
                    continue
                size = max(s["size"] for s in spans)
                bold = all((s["flags"] & 16) or "Bold" in s["font"] for s in spans)
                if len(lines) <= 2 and _is_heading(text, size, bold, body_size):
                    blocks.append(
                        Block("heading", text, number, _heading_level(text, size, body_size))
                    )
                else:
                    blocks.append(Block("text", text, number))
            # Tables that matched no text block (rare) are still kept.
            for i, (_, rows) in enumerate(tables):
                if i not in placed:
                    blocks.extend(
                        Block("table_row", r, number, table=f"p{number}t{i}") for r in rows
                    )
        return blocks, count


# ----------------------------------------------------------------------------------------------
# DOCX and TXT


def docx_blocks(data: bytes) -> list[Block]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if "word/document.xml" not in archive.namelist():
            raise ParseError("File is not a valid DOCX document.")
    doc = DocxDocument(io.BytesIO(data))
    blocks: list[Block] = []
    for n, item in enumerate(doc.iter_inner_content()):
        if hasattr(item, "text"):
            text = normalize_text(item.text)
            if not text:
                continue
            style = (item.style.name if item.style is not None else "") or ""
            if style == "Title":
                blocks.append(Block("heading", text, None, 1))
            elif style.startswith("Heading"):
                digits = "".join(ch for ch in style if ch.isdigit())
                blocks.append(Block("heading", text, None, min(4, int(digits or 1) + 1)))
            else:
                blocks.append(Block("text", text, None))
        else:
            raw = [[cell.text for cell in row.cells] for row in item.rows]
            blocks.extend(Block("table_row", r, None, table=f"t{n}") for r in table_rows(raw))
    return blocks


def txt_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    for paragraph in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [ln.strip() for ln in paragraph.split("\n") if ln.strip()]
        if not lines:
            continue
        first = lines[0]
        looks_heading = (
            len(first) <= 80
            and not first.endswith((".", ",", ";"))
            and (
                (first.isupper() and sum(c.isalpha() for c in first) >= 3)
                or bool(NUMBERED_HEADING.match(first))
            )
        )
        if looks_heading:
            blocks.append(Block("heading", normalize_text(first), None, 2))
            lines = lines[1:]
        if lines:
            blocks.append(Block("text", normalize_text(" ".join(lines)), None))
    return blocks


def parse_blocks(
    data: bytes, extension: str, max_chars: int, max_pages: int
) -> tuple[list[Block], int | None]:
    try:
        if extension == ".pdf":
            blocks, count = pdf_blocks(data, max_pages)
        elif extension == ".docx":
            blocks, count = docx_blocks(data), None
        elif extension == ".txt":
            blocks, count = txt_blocks(data.decode("utf-8-sig", errors="strict")), None
        else:
            raise ParseError("Unsupported document format.")
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError("Document could not be parsed. Check its format and encoding.") from exc
    if sum(len(b.text) for b in blocks) > max_chars:
        raise ParseError("Document exceeds the extracted text limit.")
    if not blocks:
        raise ParseError("Document contains no extractable text.")
    return blocks, count

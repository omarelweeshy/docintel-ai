import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.errors import AppError

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


@dataclass(frozen=True)
class StoredUpload:
    filename: str
    name: str
    content_type: str
    size: int
    sha256: str
    data: bytes


class FileStorage:
    def __init__(self, root: Path, max_bytes: int):
        self.root = root.resolve()
        self.max_bytes = max_bytes

    def path(self, name: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}\.(pdf|docx|txt)", name):
            raise AppError("invalid_storage_name", "Invalid storage reference.", 500)
        return self.root / name

    async def save(self, upload: UploadFile) -> StoredUpload:
        filename = (upload.filename or "").replace("\\", "/").split("/")[-1]
        filename = re.sub(r"[\x00-\x1f\x7f]", "", filename)[:255]
        extension = Path(filename).suffix.lower()
        mime = (upload.content_type or "").split(";")[0].lower()
        if extension not in MIME_TYPES or mime not in {
            MIME_TYPES[extension],
            "application/octet-stream",
        }:
            raise AppError(
                "invalid_file_type",
                "Upload a PDF, DOCX, or UTF-8 TXT with a matching MIME type.",
                415,
            )
        buffer = bytearray()
        while block := await upload.read(65536):
            buffer.extend(block)
            if len(buffer) > self.max_bytes:
                raise AppError("file_too_large", "File exceeds the configured upload limit.", 413)
        data = bytes(buffer)
        if not data:
            raise AppError("empty_file", "File is empty.", 422)
        if extension == ".pdf" and not data.startswith(b"%PDF-"):
            raise AppError("invalid_file", "PDF signature does not match its extension.", 422)
        if extension == ".docx" and not data.startswith(b"PK"):
            raise AppError("invalid_file", "DOCX signature does not match its extension.", 422)
        if extension == ".txt":
            try:
                data.decode("utf-8-sig")
                if b"\x00" in data:
                    raise ValueError("Binary text")
            except (UnicodeDecodeError, ValueError) as exc:
                raise AppError("invalid_file", "TXT must contain UTF-8 text.", 422) from exc
        name = uuid4().hex + extension
        self.root.mkdir(parents=True, exist_ok=True)
        self.path(name).write_bytes(data)
        return StoredUpload(
            filename, name, MIME_TYPES[extension], len(data), hashlib.sha256(data).hexdigest(), data
        )

    def delete(self, name: str) -> None:
        self.path(name).unlink(missing_ok=True)

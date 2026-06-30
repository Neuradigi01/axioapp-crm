import os
import uuid
from datetime import datetime

from fastapi import UploadFile

from config import STATIC_DIR
from src.constants import messages
from src.constants.file_types import (
    ALLOWED_EXTENSIONS,
    BLOCKED_EXTENSIONS,
    FILE_MAGIC_BYTES,
    MAX_FILE_SIZE_BYTES,
    MIME_EXTENSION_MAP,
    TEXT_EXTENSIONS,
)


class FileValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _detect_file_type(content: bytes) -> str | None:
    """
    Detect actual file type from magic bytes.
    Returns the MIME type string if recognized, None otherwise.
    """
    for magic, mime in FILE_MAGIC_BYTES.items():
        if content[: len(magic)] == magic:
            # WebP: RIFF container must also contain 'WEBP' at offset 8
            if magic == b"RIFF":
                if len(content) >= 12 and content[8:12] == b"WEBP":
                    return mime
                continue
            return mime
    return None


async def validate_file(
    file: UploadFile,
    allowed_extensions: set[str] = ALLOWED_EXTENSIONS,
    max_size_bytes: int = MAX_FILE_SIZE_BYTES,
) -> tuple[bytes, str]:
    """
    Validate a single uploaded file: extension whitelist, size limit, and magic byte check.

    Args:
        file: The uploaded file.
        allowed_extensions: Set of allowed extensions (e.g., IMAGE_EXTENSIONS for profile pics).
        max_size_bytes: Maximum file size in bytes.

    Returns (file_content, extension) on success.
    Raises FileValidationError on failure.
    """
    if not file or not file.filename:
        raise FileValidationError("No file provided!")

    # 1. Validate extension
    _, ext = os.path.splitext(file.filename.lower())

    if ext in BLOCKED_EXTENSIONS:
        raise FileValidationError(messages.FILE_TYPE_NOT_ALLOWED)

    if ext not in allowed_extensions:
        raise FileValidationError(messages.FILE_TYPE_NOT_ALLOWED)

    # 2. Read content and validate size
    content = await file.read()

    if len(content) == 0:
        raise FileValidationError(messages.FILE_EMPTY)

    if len(content) > max_size_bytes:
        raise FileValidationError(messages.FILE_TOO_LARGE)

    # 3. Magic byte validation for binary formats
    if ext not in TEXT_EXTENSIONS:
        detected_mime = _detect_file_type(content)
        if detected_mime is None:
            raise FileValidationError(messages.FILE_CONTENT_MISMATCH)
        # Verify the detected MIME type is compatible with the claimed extension
        valid_extensions = MIME_EXTENSION_MAP.get(detected_mime, set())
        if ext not in valid_extensions:
            raise FileValidationError(messages.FILE_CONTENT_MISMATCH)

    return content, ext


def save_file(content: bytes, ext: str, original_filename: str, subfolder: str = "tickets") -> dict:
    """
    Save file content to disk with a UUID-based filename.

    Args:
        content: Raw file bytes.
        ext: File extension (e.g., '.jpg').
        original_filename: Original filename from the upload.
        subfolder: Subdirectory under uploads/ (e.g., 'tickets', 'profiles').

    Returns dict with keys: stored_name, file_name, file_size, mime_type, file_path.
    """
    # Build save path: static/uploads/<subfolder>/YYYY-MM/
    date_folder = datetime.now().strftime("%Y-%m")
    upload_dir = os.path.join(STATIC_DIR, "uploads", subfolder, date_folder)
    os.makedirs(upload_dir, exist_ok=True)

    stored_name = f"{uuid.uuid4().hex}{ext}"
    full_path = os.path.join(upload_dir, stored_name)

    with open(full_path, "wb") as f:
        f.write(content)

    # Determine MIME type from magic bytes or fallback for text types
    detected_mime = _detect_file_type(content)
    if detected_mime is None:
        mime_map = {
            ".txt": "text/plain",
            ".csv": "text/csv",
            ".rtf": "application/rtf",
            ".svg": "image/svg+xml",
        }
        detected_mime = mime_map.get(ext, "application/octet-stream")

    relative_path = f"uploads/{subfolder}/{date_folder}/{stored_name}"

    return {
        "stored_name": stored_name,
        "file_name": original_filename,
        "file_size": len(content),
        "mime_type": detected_mime,
        "file_path": relative_path,
    }


def delete_file(file_path: str) -> bool:
    """
    Delete a file from disk.
    file_path should be relative to STATIC_DIR (e.g., uploads/profiles/2026-03/abc.jpg).
    Returns True if deleted, False if not found.
    """
    if not file_path:
        return False

    full_path = os.path.join(STATIC_DIR, file_path)
    if os.path.isfile(full_path):
        os.remove(full_path)
        return True
    return False


def get_file_path(stored_name: str, subfolder: str = "tickets") -> str | None:
    """
    Resolve the full filesystem path for a stored file.
    Searches in uploads/<subfolder>/ subdirectories.
    Returns the full path if found, None otherwise.
    """
    base_dir = os.path.join(STATIC_DIR, "uploads", subfolder)
    if not os.path.isdir(base_dir):
        return None

    for date_folder in os.listdir(base_dir):
        full_path = os.path.join(base_dir, date_folder, stored_name)
        if os.path.isfile(full_path):
            return full_path

    return None

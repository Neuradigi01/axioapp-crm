"""Tests for the pre-storage file-validation helpers
(``tasks/ai-assistants`` Step 10; Attacker H5+H6, Cases §10-14).

Pure Python — no DB, no Celery. The router calls
``validate_upload()`` before writing to storage; these tests pin the
exact failure reasons the frontend surfaces to localise messages.
"""

from __future__ import annotations

import hashlib
import io

import pytest

from src.app.core.ai_assistants.file_upload import (
    FileValidationError,
    ValidatedUpload,
    validate_upload,
)


def _plain_utf8(body: str) -> bytes:
    return body.encode("utf-8")


def _fake_pdf(pages: int = 1) -> bytes:
    """Minimal-viable PDF byte sequence — starts with ``%PDF-1.4``
    which is what ``filetype`` sniffs for. Not a valid PDF for
    parsing; enough for the magic-byte check to pass."""
    header = b"%PDF-1.4\n"
    body = b"1 0 obj\n<<>>\nendobj\n" * pages
    trailer = b"trailer<<>>\n%%EOF"
    return header + body + trailer


# --- Size checks ---------------------------------------------------------


def test_empty_upload_rejected() -> None:
    with pytest.raises(FileValidationError) as exc:
        validate_upload(filename="empty.txt", data=b"")
    assert exc.value.reason == "empty_file"


def test_oversized_upload_rejected() -> None:
    huge = b"a" * (90 * 1024 * 1024 + 1)
    with pytest.raises(FileValidationError) as exc:
        validate_upload(filename="big.txt", data=huge)
    assert exc.value.reason == "file_too_large"


# --- Filename hygiene ----------------------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    [
        "path/traversal.txt",
        "path\\backslash.txt",
        "control\x00char.txt",
        "control\x1fchar.txt",
        "control\x7fchar.txt",
        "wild<card>.txt",
        "colon:name.txt",
        'quote"name.txt',
        "pipe|name.txt",
        "question?.txt",
        "star*.txt",
    ],
)
def test_illegal_filename_chars_rejected(bad_name: str) -> None:
    with pytest.raises(FileValidationError) as exc:
        validate_upload(filename=bad_name, data=_plain_utf8("hi"))
    assert exc.value.reason == "illegal_filename_chars"


@pytest.mark.parametrize(
    "reserved",
    ["CON", "NUL", "AUX", "PRN", "COM1.txt", "LPT9.pdf", "con.pdf", "aux"],
)
def test_windows_reserved_names_rejected(reserved: str) -> None:
    with pytest.raises(FileValidationError) as exc:
        validate_upload(filename=reserved, data=_plain_utf8("hi"))
    assert exc.value.reason == "windows_reserved_name"


# --- Magic-byte sniff ---------------------------------------------------


def test_exe_renamed_to_pdf_rejected() -> None:
    """PE binaries start with ``MZ`` — ``filetype`` recognises them
    as ``application/x-msdownload``; the allowed-list check
    rejects."""
    fake_exe = b"MZ\x90\x00" + b"\x00" * 1024
    with pytest.raises(FileValidationError) as exc:
        validate_upload(filename="innocent.pdf", data=fake_exe)
    assert exc.value.reason == "unsupported_mime"


def test_random_binary_renamed_to_txt_rejected() -> None:
    """Bytes that aren't a known type AND don't decode as UTF-8 are
    refused — no silently corrupted text corpora."""
    random_binary = bytes(range(256)) * 4
    with pytest.raises(FileValidationError) as exc:
        validate_upload(filename="mystery.txt", data=random_binary)
    assert exc.value.reason == "unrecognised_file_type"


def test_valid_pdf_accepted() -> None:
    pdf = _fake_pdf()
    result = validate_upload(filename="doc.pdf", data=pdf)
    assert isinstance(result, ValidatedUpload)
    assert result.sniffed_mime == "application/pdf"
    assert result.size_bytes == len(pdf)
    assert result.content_hash == hashlib.sha256(pdf).digest()


def test_plain_utf8_text_accepted() -> None:
    body = _plain_utf8("The quick brown fox jumps over the lazy dog.")
    result = validate_upload(filename="fable.txt", data=body)
    assert result.sniffed_mime == "text/plain"
    assert result.original_filename == "fable.txt"


def test_utf8_text_with_bom_accepted() -> None:
    """Windows-native editors save UTF-8 with a BOM prefix; that's
    still valid UTF-8 so the sniff-fallback path accepts it."""
    body = b"\xef\xbb\xbf" + _plain_utf8("hello")
    result = validate_upload(filename="withbom.txt", data=body)
    assert result.sniffed_mime == "text/plain"


# --- SHA-256 fingerprint ------------------------------------------------


def test_same_bytes_same_hash() -> None:
    body = _plain_utf8("dedup me")
    a = validate_upload(filename="a.txt", data=body)
    b = validate_upload(filename="b.txt", data=body)
    assert a.content_hash == b.content_hash


def test_different_bytes_different_hash() -> None:
    a = validate_upload(filename="a.txt", data=_plain_utf8("one"))
    b = validate_upload(filename="b.txt", data=_plain_utf8("two"))
    assert a.content_hash != b.content_hash

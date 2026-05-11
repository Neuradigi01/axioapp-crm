"""Tests for the layered bcrypt password helper."""
from __future__ import annotations

from src.app.shared.security.password import hash_password, verify_password


def test_hash_password_is_not_plaintext():
    hashed = hash_password("S3cret!Pass")
    assert hashed != "S3cret!Pass"
    assert hashed.startswith("$2")  # bcrypt prefix


def test_hash_password_changes_per_call():
    """Bcrypt salts each call; same input → different hashes."""
    a = hash_password("same-input")
    b = hash_password("same-input")
    assert a != b


def test_verify_password_roundtrip():
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("the-right-one")
    assert verify_password("not-it", hashed) is False

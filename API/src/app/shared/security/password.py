"""Bcrypt password hashing for FurnitureCRM core users.

Ported from `src/core/security/password.py` so the layered app has its
own canonical entry point. Behaviour is identical; same bcrypt library,
same salt strategy. The legacy module continues to back the existing
auth pages until Step 1.6 finishes the auth migration.
"""

from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

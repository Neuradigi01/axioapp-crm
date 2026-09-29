"""Storage configuration read from the environment.

* ``STORAGE_BACKEND`` — ``local`` (default) or ``r2``.
* ``STORAGE_ROOT`` — local-disk root. Holds every blob under
  ``local``; under ``r2`` it still holds the short-lived Mailgun
  staging folders (``pending-inbound/``, ``pending-events/``,
  ``{org}/staging/``).
* ``R2_ACCOUNT_ID`` / ``R2_ACCESS_KEY_ID`` / ``R2_SECRET_ACCESS_KEY`` /
  ``R2_BUCKET`` — required when ``STORAGE_BACKEND=r2``. Secrets come
  from ``secrets.<env>.enc.env`` via ``sops exec-env``.

Values are read on every call (not cached at import) so tests can
point ``STORAGE_ROOT`` at a tempdir with ``monkeypatch.setenv``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

STORAGE_BACKENDS = ("local", "r2")
R2_REQUIRED_VARS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")


class StorageConfigError(RuntimeError):
    """The storage configuration is incomplete or invalid. Messages name
    the offending variables, never their values."""


@dataclass(frozen=True, slots=True)
class R2Settings:
    account_id: str
    access_key_id: str
    secret_access_key: str = field(repr=False)
    bucket: str

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


def storage_root() -> Path:
    """Local-disk storage root (``STORAGE_ROOT``, default ``./storage``)."""
    return Path(os.getenv("STORAGE_ROOT", "./storage"))


def storage_backend_name() -> str:
    """The configured backend name, validated against `STORAGE_BACKENDS`."""
    name = os.getenv("STORAGE_BACKEND", "local").strip().lower() or "local"
    if name not in STORAGE_BACKENDS:
        raise StorageConfigError(
            f"STORAGE_BACKEND must be one of {', '.join(STORAGE_BACKENDS)}; got {name!r}"
        )
    return name


def r2_settings() -> R2Settings:
    """Read the R2 credentials. Raises `StorageConfigError` naming every
    missing variable."""
    values = {var: os.getenv(var, "").strip() for var in R2_REQUIRED_VARS}
    missing = [var for var, value in values.items() if not value]
    if missing:
        raise StorageConfigError(f"STORAGE_BACKEND=r2 but these are not set: {', '.join(missing)}")
    return R2Settings(
        account_id=values["R2_ACCOUNT_ID"],
        access_key_id=values["R2_ACCESS_KEY_ID"],
        secret_access_key=values["R2_SECRET_ACCESS_KEY"],
        bucket=values["R2_BUCKET"],
    )

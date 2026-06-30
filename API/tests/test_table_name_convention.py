"""Pin-test: every application table in `Base.metadata` is named `tbl_*`.

Catches accidental drift back to plain names. If a future developer
adds a new model and forgets the convention documented in
`tasks/rename-tbl-prefix/naming-map.md` (and `API/docs/DATABASE_RULES.md`),
this test fails in CI and names the offender.

Allowed exceptions (each one explained):

* `users` — metadata-only shim in `src.app.core.users.models`. Kept so
  the two parked `ForeignKey("users.id")` strings in `audit/models.py`
  and `auth/models.py` continue to resolve via `Base.metadata` (the
  physical `users` table was dropped by migration 0037; see
  `tasks/rename-tbl-prefix/naming-map.md` §8).
* Any table name starting with `_test_` — pytest sandbox tables in
  `tests/test_pagination.py`, `tests/test_tenant_filter.py`, etc.
  Created with `Base.metadata.create_all` per-test, dropped at
  teardown, never deployed.
"""

from __future__ import annotations

import importlib
import pkgutil

import src.app as app_pkg
from src.app.shared.db import Base

_ALLOWED_EXCEPTIONS = {"users"}


def _import_all_model_modules() -> None:
    """Walk every package under `src.app` and import any module whose
    name ends in `.models`. Forces `Base.metadata` to register every
    declared mapper so we can introspect the full table set."""
    for _finder, name, _ispkg in pkgutil.walk_packages(app_pkg.__path__, prefix="src.app."):
        if name.endswith(".models") or name.endswith("_models"):
            try:
                importlib.import_module(name)
            except ImportError:
                # Sub-packages without a `models` submodule occasionally
                # trip this; ignore — they don't contribute to metadata.
                continue


def test_every_app_table_uses_tbl_prefix() -> None:
    _import_all_model_modules()

    offenders = sorted(
        t.name
        for t in Base.metadata.tables.values()
        if not t.name.startswith("tbl_")
        and not t.name.startswith("_test_")
        and t.name not in _ALLOWED_EXCEPTIONS
    )

    assert offenders == [], (
        f"Tables in Base.metadata without `tbl_` prefix: {offenders}. "
        "Every application table must be named `tbl_<snake_name>` "
        "(see tasks/rename-tbl-prefix/naming-map.md). If this is "
        "intentional, add the name to `_ALLOWED_EXCEPTIONS` with a "
        "comment explaining why."
    )

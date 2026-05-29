"""Contact bulk import — XLSX / CSV upload → dry-run → commit (Step 3.5.10).

The flow is intentionally synchronous in v1: file-size cap of 5 MB /
10,000 rows keeps inline processing well within the request timeout.
A future step can route through Celery if the cap rises.

Public re-exports keep the import surface small; the router is the
only caller outside this package."""
from src.app.core.contacts.imports.service import (
    MAX_FILE_SIZE_BYTES,
    MAX_ROW_COUNT,
    commit_import,
    dry_run_import,
    upload_file,
)

__all__ = [
    "MAX_FILE_SIZE_BYTES",
    "MAX_ROW_COUNT",
    "commit_import",
    "dry_run_import",
    "upload_file",
]

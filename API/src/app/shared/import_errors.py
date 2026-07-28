"""Shared error-record + `errors.csv` writer for bulk imports.

Steps 8–10 of the application-updates track (contacts / leads / catalog
CSV imports) all produce a downloadable error report with the same
column shape:

    <original CSV columns…>, __row_number, __column, __value, __error_reason

Having one writer means the three imports cannot drift in output shape,
and a downstream tool that parses one file can parse all three.

Nothing here touches the database — this module is a formatting helper.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


ROW_NUMBER_COLUMN = "__row_number"
COLUMN_COLUMN = "__column"
VALUE_COLUMN = "__value"
REASON_COLUMN = "__error_reason"

_APPENDED_COLUMNS = (ROW_NUMBER_COLUMN, COLUMN_COLUMN, VALUE_COLUMN, REASON_COLUMN)


@dataclass
class ImportRowError:
    """One rejected row's forensic record.

    Named `ImportRowError` (not `ImportError`) so the class does not
    shadow the built-in `ImportError` exception in importing modules.
    """

    row_number: int
    column: str | None
    value: str | None
    reason: str


def write_errors_csv(
    original_headers: Sequence[str],
    original_rows: Sequence[Mapping[str, object]],
    errors: Iterable[ImportRowError],
) -> bytes:
    """Emit a CSV of the failed rows with `__row_number` / column / value / reason columns appended.

    `original_rows` is indexed by 1-based `row_number` — index 1 is the
    first data row (headers occupy row 0 conceptually). Rows whose row
    number does not appear in `errors` are skipped so the report only
    carries the failures.

    Returns UTF-8 bytes suitable for a `StreamingResponse` body.
    """
    buffer = io.StringIO()
    fieldnames = [*original_headers, *_APPENDED_COLUMNS]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for err in errors:
        original = (
            original_rows[err.row_number - 1]
            if 0 < err.row_number <= len(original_rows)
            else {}
        )
        row: dict[str, object] = {
            header: original.get(header, "") for header in original_headers
        }
        row[ROW_NUMBER_COLUMN] = err.row_number
        row[COLUMN_COLUMN] = err.column or ""
        row[VALUE_COLUMN] = "" if err.value is None else err.value
        row[REASON_COLUMN] = err.reason
        writer.writerow(row)

    return buffer.getvalue().encode("utf-8")

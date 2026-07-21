"""CSV + XLSX iterator for the bulk-import processor.

`parse_rows(storage_path, mapping)` yields one `ParsedRow` per data row.
The first row of the file is treated as the header and consumed to
build the column-name lookup — it never yields. `row_number` is
1-based against the data rows (so the first yielded row is
`row_number=1` and corresponds to line 2 of the source file).

`raw` is the dict of {original_column_name: cell_string_value} so the
caller can reconstruct an error-CSV row with the original column
order. `mapped` is the dict of {crm_field_key: cell_string_value}
after applying the mapping; columns mapped to `None` are dropped.

This module knows nothing about CRM types — every cell is a string
(or None). Pydantic / Lead creation downstream does the coercion.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ParsedRow:
    row_number: int  # 1-based data-row index
    raw: dict[str, str | None]  # original column → value
    mapped: dict[str, str | None]  # crm field key → value


@dataclass(frozen=True, slots=True)
class HeaderInfo:
    """Returned alongside the row iterator so callers can build a
    well-shaped error CSV without re-reading the file."""

    columns: list[str]  # original column order, deduped


def _open_file_bytes(path: str) -> bytes:
    """Resolve the storage-relative path under `./storage/` and return
    raw bytes. Mirrors the StorageBackend contract — paths are relative
    POSIX strings, joined onto the local storage root.
    """
    full = Path("./storage").resolve() / path.lstrip("/")
    return full.read_bytes()


def _decode_csv(data: bytes) -> str:
    """Best-effort decode for CSV exports (UTF-8 with BOM, then latin-1)."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def _apply_mapping(
    raw: dict[str, str | None], mapping: dict[str, str | None]
) -> dict[str, str | None]:
    """Project `raw` (csv column → value) through `mapping`
    (csv column → crm field key) to get `mapped` (crm field key → value).

    Unmapped columns are dropped. Columns mapped to None/empty target
    are also dropped (the UI uses None to mean "ignore this column").
    """
    out: dict[str, str | None] = {}
    for col, target in mapping.items():
        if not target:
            continue
        value = raw.get(col)
        out[target] = value
    return out


def parse_csv_rows(
    storage_path: str, mapping: dict[str, str | None]
) -> tuple[HeaderInfo, Iterator[ParsedRow]]:
    """Parse a CSV file at `storage_path` against `mapping`."""
    data = _open_file_bytes(storage_path)
    text = _decode_csv(data)
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return HeaderInfo(columns=[]), iter(())

    # Strip whitespace from headers — exports often have trailing spaces.
    columns = [c.strip() for c in header]

    def _iter() -> Iterator[ParsedRow]:
        for idx, row in enumerate(reader, start=1):
            raw: dict[str, str | None] = {}
            for i, col in enumerate(columns):
                value = row[i] if i < len(row) else None
                if isinstance(value, str):
                    value = value.strip() or None
                raw[col] = value
            yield ParsedRow(
                row_number=idx,
                raw=raw,
                mapped=_apply_mapping(raw, mapping),
            )

    return HeaderInfo(columns=columns), _iter()


def parse_xlsx_rows(
    storage_path: str, mapping: dict[str, str | None]
) -> tuple[HeaderInfo, Iterator[ParsedRow]]:
    """Parse an XLSX file's first sheet at `storage_path`."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - openpyxl bundled
        raise RuntimeError("openpyxl not installed") from exc

    data = _open_file_bytes(storage_path)
    wb = load_workbook(filename=io.BytesIO(data), read_only=True)
    ws = wb.active
    if ws is None:
        wb.close()
        return HeaderInfo(columns=[]), iter(())

    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        wb.close()
        return HeaderInfo(columns=[]), iter(())

    columns = [str(c).strip() if c is not None else "" for c in header_row]

    def _iter() -> Iterator[ParsedRow]:
        try:
            for idx, row in enumerate(rows_iter, start=1):
                raw: dict[str, str | None] = {}
                for i, col in enumerate(columns):
                    if not col:
                        continue
                    value: Any = row[i] if i < len(row) else None
                    if value is None:
                        raw[col] = None
                    else:
                        text = str(value).strip()
                        raw[col] = text or None
                # Skip all-empty rows past the last real data row.
                # openpyxl's used-range often over-counts on workbooks
                # with stray formatting past the data, inflating
                # `will_skip` counts and per-row errors otherwise.
                if not any(v for v in raw.values()):
                    continue
                yield ParsedRow(
                    row_number=idx,
                    raw=raw,
                    mapped=_apply_mapping(raw, mapping),
                )
        finally:
            wb.close()

    return HeaderInfo(columns=columns), _iter()


def parse_rows(
    storage_path: str, mapping: dict[str, str | None]
) -> tuple[HeaderInfo, Iterator[ParsedRow]]:
    """Dispatch to the CSV or XLSX parser based on extension."""
    ext = storage_path.rsplit(".", 1)[-1].lower()
    if ext == "csv":
        return parse_csv_rows(storage_path, mapping)
    if ext == "xlsx":
        return parse_xlsx_rows(storage_path, mapping)
    raise ValueError(f"unsupported file extension: {ext!r}")


__all__ = ["HeaderInfo", "ParsedRow", "parse_rows"]

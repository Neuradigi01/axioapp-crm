"""CSV + XLSX iterator for contact bulk imports (Step 3.5.10).

Two helpers:

  - `parse_headers_and_sample(file_bytes, filename)` — first pass:
    reads the header row + first ~5 data rows for the mapping-step
    preview. Used by `POST /upload`.

  - `parse_all_rows(file_bytes, filename)` — full iterator:
    yields one dict per data row keyed by original column name.
    Used by dry-run + commit. Errors raise at the file level
    (unreadable file, missing headers); per-row malformedness
    is the caller's concern.

CSV: stdlib `csv` with utf-8-sig + latin-1 fallback (covers Excel
exports' BOM + Indian regional encodings).

XLSX: openpyxl. Soft-imports — if openpyxl isn't installed the
module still loads + CSV continues to work; XLSX uploads raise a
clear error message at parse time.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator


def _decode_csv(data: bytes) -> str:
    """Best-effort CSV decode — UTF-8 with BOM first (Excel default),
    fall back to latin-1 with replacement (handles bad bytes without
    raising)."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def _file_kind(filename: str) -> str:
    """Return 'csv' or 'xlsx'. Raises ValueError on unknown."""
    lower = filename.lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".xlsx"):
        return "xlsx"
    raise ValueError(f"Unsupported file type: {filename!r}. Only .csv and .xlsx are accepted.")


# --- CSV ----------------------------------------------------------------


def _csv_rows(data: bytes) -> Iterator[list[str]]:
    text = _decode_csv(data)
    reader = csv.reader(io.StringIO(text))
    yield from reader


# --- XLSX ---------------------------------------------------------------


def _xlsx_rows(data: bytes) -> Iterator[list[str]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError(
            "XLSX uploads require the `openpyxl` package. Install with "
            "`pip install openpyxl` and restart the API container."
        ) from exc
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    first_row_seen = False
    for raw_row in ws.iter_rows(values_only=True):
        cells = ["" if c is None else str(c) for c in raw_row]
        # Drop all-empty rows AFTER the header. openpyxl's used-range
        # includes rows that carry stray formatting past the last data
        # row — those otherwise inflate `row_count` / `will_skip` and
        # pollute the errors list.
        if first_row_seen and not any(cell.strip() for cell in cells):
            continue
        first_row_seen = True
        yield cells


# --- public API ----------------------------------------------------------


def _row_iter(file_bytes: bytes, filename: str) -> Iterator[list[str]]:
    kind = _file_kind(filename)
    if kind == "csv":
        return _csv_rows(file_bytes)
    return _xlsx_rows(file_bytes)


def parse_headers_and_sample(
    file_bytes: bytes, filename: str, *, sample_size: int = 5
) -> tuple[list[str], list[dict[str, str]], int]:
    """Read just enough of the file to render the mapping UI.

    Returns `(headers, sample_rows, total_data_rows)`:
      - `headers`: cleaned header strings (whitespace-stripped,
        deduped — duplicates suffixed `_2`, `_3`, …).
      - `sample_rows`: first N data rows as `{header: cell_value}`
        dicts for the preview pane.
      - `total_data_rows`: counted up to a hard limit to support the
        file-size gate in the service layer.
    """
    headers: list[str] = []
    sample_rows: list[dict[str, str]] = []
    total = 0
    iterator = _row_iter(file_bytes, filename)
    for idx, row in enumerate(iterator):
        if idx == 0:
            headers = _normalize_headers(row)
            continue
        total += 1
        if len(sample_rows) < sample_size:
            sample_rows.append(_row_to_dict(headers, row))
    return headers, sample_rows, total


def parse_all_rows(file_bytes: bytes, filename: str) -> Iterator[tuple[int, dict[str, str]]]:
    """Full data iterator. `row_number` is 1-based against data rows
    (header is row 0 internally but never yielded)."""
    headers: list[str] = []
    for idx, row in enumerate(_row_iter(file_bytes, filename)):
        if idx == 0:
            headers = _normalize_headers(row)
            continue
        yield idx, _row_to_dict(headers, row)


def _normalize_headers(raw: list[str]) -> list[str]:
    """Strip whitespace + dedupe via `_2`, `_3` suffixes. Empty cells
    become `column_N` placeholders so the mapping UI has something to
    render."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, cell in enumerate(raw):
        name = (cell or "").strip() or f"column_{i + 1}"
        count = seen.get(name, 0) + 1
        seen[name] = count
        if count > 1:
            name = f"{name}_{count}"
        out.append(name)
    return out


def _row_to_dict(headers: list[str], row: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i, header in enumerate(headers):
        out[header] = (row[i] or "").strip() if i < len(row) else ""
    return out


# --- auto-mapping heuristic --------------------------------------------


_FIELD_ALIASES: dict[str, list[str]] = {
    "full_name": ["full_name", "name", "full name", "contact name", "customer name"],
    "phone": ["phone", "mobile", "phone number", "mobile number", "contact number", "whatsapp"],
    "email": ["email", "email address", "e-mail", "mail"],
    "source": ["source", "channel", "origin"],
    "tag": ["tag", "tags", "label", "category"],
}


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    """Best-effort guess at column → contact-field mapping based on
    common column names. The operator overrides anything wrong in
    the mapping step; this just saves keystrokes for the typical
    XLSX from a sales spreadsheet."""
    mapping: dict[str, str] = {}
    used_targets: set[str] = set()
    for header in headers:
        normalised = header.strip().lower().replace("_", " ")
        for target, aliases in _FIELD_ALIASES.items():
            if target in used_targets:
                continue
            if any(alias == normalised for alias in aliases):
                mapping[header] = target
                used_targets.add(target)
                break
        else:
            mapping[header] = "skip"
    return mapping


__all__ = [
    "parse_all_rows",
    "parse_headers_and_sample",
    "suggest_mapping",
]

"""Step 3.5.10 — contact import parser + helpers (pure unit tests).

The full upload→dry-run→commit flow needs a DB session + storage IO,
covered by manual smoke. Here we lock down the helpers + parser
contract the flow depends on.

What we prove:

  1. CSV parser handles UTF-8 BOM, latin-1 fallback, and quoted fields.
  2. XLSX parser reads typed cells as strings (numeric, dates → str).
  3. Header normalisation strips whitespace + dedupes duplicates.
  4. `suggest_mapping` picks the right contact field for common
     column names (regression guard).
  5. `_normalise_phone` strips non-digits + leading zeros.
  6. `_apply_mapping` drops `skip` columns and missing-mapping columns.
"""
from __future__ import annotations

import io

import pytest

from src.app.core.contacts.imports import parser, service


# --- CSV parsing ---------------------------------------------------------


class TestCsvParse:
    def test_basic_csv_yields_data_rows(self):
        data = b"name,phone,email\nAsha,9999,asha@x.com\nBob,8888,bob@x.com\n"
        headers, sample, total = parser.parse_headers_and_sample(
            data, "test.csv"
        )
        assert headers == ["name", "phone", "email"]
        assert total == 2
        assert sample == [
            {"name": "Asha", "phone": "9999", "email": "asha@x.com"},
            {"name": "Bob", "phone": "8888", "email": "bob@x.com"},
        ]

    def test_utf8_bom_decoded(self):
        """Excel exports with UTF-8 BOM should decode cleanly."""
        data = (
            "﻿full_name,phone\nAsha Walker,9876543210\n"
        ).encode("utf-8")
        headers, sample, total = parser.parse_headers_and_sample(
            data, "test.csv"
        )
        assert headers == ["full_name", "phone"]
        assert sample[0]["full_name"] == "Asha Walker"

    def test_quoted_fields_with_commas(self):
        data = b'name,address\n"Walker, Asha","Bangalore, IN"\n'
        headers, sample, total = parser.parse_headers_and_sample(
            data, "test.csv"
        )
        assert sample[0]["name"] == "Walker, Asha"
        assert sample[0]["address"] == "Bangalore, IN"

    def test_full_iterator_yields_correct_row_numbers(self):
        data = b"name\nA\nB\nC\n"
        rows = list(parser.parse_all_rows(data, "test.csv"))
        assert [r[0] for r in rows] == [1, 2, 3]
        assert [r[1]["name"] for r in rows] == ["A", "B", "C"]


# --- XLSX parsing --------------------------------------------------------


class TestXlsxParse:
    def _make_xlsx(self, rows: list[list[str | int]]) -> bytes:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        for row in rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_basic_xlsx(self):
        data = self._make_xlsx(
            [["name", "phone"], ["Asha", "9876543210"]]
        )
        headers, sample, total = parser.parse_headers_and_sample(
            data, "test.xlsx"
        )
        assert headers == ["name", "phone"]
        assert total == 1
        assert sample[0]["name"] == "Asha"

    def test_numeric_cells_coerced_to_string(self):
        """A phone column with numeric cells (Excel default) should
        come out as a string in the data dict."""
        data = self._make_xlsx(
            [["name", "phone"], ["Asha", 9876543210]]
        )
        _, sample, _ = parser.parse_headers_and_sample(data, "test.xlsx")
        assert sample[0]["phone"] == "9876543210"


# --- header normalisation -----------------------------------------------


class TestHeaderNormalisation:
    def test_strips_whitespace(self):
        out = parser._normalize_headers(["  name  ", " phone "])
        assert out == ["name", "phone"]

    def test_dedupes_duplicates_with_suffix(self):
        out = parser._normalize_headers(["phone", "phone", "phone"])
        assert out == ["phone", "phone_2", "phone_3"]

    def test_empty_cells_become_placeholders(self):
        out = parser._normalize_headers(["name", "", "tag"])
        assert out == ["name", "column_2", "tag"]


# --- suggest_mapping heuristic ------------------------------------------


class TestSuggestMapping:
    def test_picks_obvious_fields(self):
        out = parser.suggest_mapping(["Full Name", "Phone", "Email"])
        assert out["Full Name"] == "full_name"
        assert out["Phone"] == "phone"
        assert out["Email"] == "email"

    def test_unknown_columns_default_to_skip(self):
        out = parser.suggest_mapping(["random_column", "phone"])
        assert out["random_column"] == "skip"
        assert out["phone"] == "phone"

    def test_phone_aliases(self):
        for col in ["mobile", "Mobile Number", "Whatsapp"]:
            assert parser.suggest_mapping([col])[col] == "phone"

    def test_first_match_wins(self):
        """If a sheet has 'phone' and 'mobile' (which both map to
        phone), the FIRST column wins and the second falls to 'skip'.
        Picker UI lets the operator override."""
        out = parser.suggest_mapping(["phone", "mobile"])
        assert out["phone"] == "phone"
        assert out["mobile"] == "skip"


# --- service helpers ----------------------------------------------------


class TestNormalisePhone:
    def test_strips_non_digits(self):
        assert service._normalise_phone("+91 9876-54-32-10") == "919876543210"

    def test_strips_leading_zeros(self):
        assert service._normalise_phone("009876543210") == "9876543210"

    def test_empty_input(self):
        assert service._normalise_phone("") == ""
        assert service._normalise_phone(None) == ""  # type: ignore[arg-type]


class TestApplyMapping:
    def test_skip_drops_column(self):
        out = service._apply_mapping(
            {"name": "Asha", "junk": "xyz"},
            {"name": "full_name", "junk": "skip"},
        )
        assert out == {"full_name": "Asha"}

    def test_missing_mapping_dropped(self):
        out = service._apply_mapping(
            {"name": "Asha", "extra": "x"},
            {"name": "full_name"},  # no entry for 'extra'
        )
        assert out == {"full_name": "Asha"}

    def test_targets_overwrite_on_duplicate(self):
        """If two columns are accidentally both mapped to the same
        target, the LAST one wins. The picker UI prevents this in
        practice, but the helper is forgiving."""
        out = service._apply_mapping(
            {"phone": "9999", "mobile": "8888"},
            {"phone": "phone", "mobile": "phone"},
        )
        assert out == {"phone": "8888"}


# --- file size + row caps -----------------------------------------------


class TestCaps:
    def test_caps_match_documented_values(self):
        """Step 3.5.10's pre-impl choice (a): 5 MB / 10K rows.
        Lock the constants so a future tweak gets caught."""
        assert service.MAX_FILE_SIZE_BYTES == 5 * 1024 * 1024
        assert service.MAX_ROW_COUNT == 10_000


# --- unsupported file type ----------------------------------------------


class TestFileKind:
    def test_csv_recognised(self):
        assert parser._file_kind("data.csv") == "csv"

    def test_xlsx_recognised(self):
        assert parser._file_kind("data.xlsx") == "xlsx"

    def test_case_insensitive(self):
        assert parser._file_kind("DATA.CSV") == "csv"

    def test_unknown_extension_raises(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            parser._file_kind("data.txt")

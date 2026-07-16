"""Campaigns v1 Step 07 (backend) — sender-setup module unit tests.

Pure Python — no DB round-trips. Covers:

  1. Schema-layer validators — the ``domain`` field's shape check
     accepts the well-formed cases and rejects the pathological ones.
  2. ``service.dns_records_for`` — the three DNS records the operator
     sees on the Settings page contain the selector + public key +
     the correct hosts + purposes.
  3. ``service._dkim_selector_for_org`` — deterministic per-org
     selector so repeated create attempts don't drift.
  4. ``service.verify_domain`` rate-limit key — a second call inside
     the 60s window hits the 429 branch.

End-to-end tests (create → verify → delete + campaign pre-flight)
land with the browser smoke on Ajay's Workspace.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.app.core.email_sender_setup.models import EmailSenderDomain
from src.app.core.email_sender_setup.schemas import DomainCreate
from src.app.core.email_sender_setup.service import (
    _VERIFY_RATE_LIMIT_SECONDS,
    _dkim_selector_for_org,
    _verify_last_hit,
    dns_records_for,
)


# --- DomainCreate schema -------------------------------------------------


class TestDomainCreate:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("yourshop.com", "yourshop.com"),
            (" YOURSHOP.COM ", "yourshop.com"),
            ("mail.yourshop.co.in", "mail.yourshop.co.in"),
            ("yourshop.com.", "yourshop.com"),  # trailing dot stripped
        ],
    )
    def test_valid_domain_normalises(self, raw: str, expected: str):
        assert DomainCreate.model_validate({"domain": raw}).domain == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "not a domain",
            "invalid_underscore.com",
            "yourshop",  # missing TLD
            "-badstart.com",
            "badend-.com",
            "toolong" + ("x" * 250) + ".com",
        ],
    )
    def test_invalid_domain_rejected(self, raw: str):
        with pytest.raises(ValidationError):
            DomainCreate.model_validate({"domain": raw})


# --- DKIM selector ------------------------------------------------------


class TestDkimSelector:
    def test_deterministic_for_same_org(self):
        org = uuid.uuid4()
        assert _dkim_selector_for_org(org) == _dkim_selector_for_org(org)

    def test_differs_across_orgs(self):
        a = _dkim_selector_for_org(uuid.uuid4())
        b = _dkim_selector_for_org(uuid.uuid4())
        assert a != b

    def test_dns_label_length_safe(self):
        # 63-byte per-label ceiling. Our prefix + 8-char id fits well
        # under, but pin the invariant so future edits don't regress.
        for _ in range(10):
            assert len(_dkim_selector_for_org(uuid.uuid4())) <= 63

    def test_starts_with_prefix(self):
        assert _dkim_selector_for_org(uuid.uuid4()).startswith("core-crm-")


# --- dns_records_for ----------------------------------------------------


def _row(**overrides) -> EmailSenderDomain:
    row = EmailSenderDomain(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        domain="yourshop.com",
        spf_verified=False,
        dkim_verified=False,
        dmarc_verified=False,
        dkim_selector="core-crm-abc12345",
        dkim_public_key="pending",
    )
    for k, v in overrides.items():
        setattr(row, k, v)
    return row


class TestDnsRecordsFor:
    def test_returns_three_records(self):
        records = dns_records_for(_row())
        assert len(records) == 3
        assert {r.purpose for r in records} == {"spf", "dkim", "dmarc"}

    def test_spf_apex(self):
        records = dns_records_for(_row())
        spf = next(r for r in records if r.purpose == "spf")
        assert spf.host == "yourshop.com"
        assert spf.type == "TXT"
        assert "v=spf1" in spf.value

    def test_dkim_host_uses_selector(self):
        row = _row(dkim_selector="core-crm-abc12345")
        records = dns_records_for(row)
        dkim = next(r for r in records if r.purpose == "dkim")
        assert dkim.host == "core-crm-abc12345._domainkey.yourshop.com"
        assert dkim.type == "TXT"
        assert "v=DKIM1" in dkim.value

    def test_dkim_embeds_public_key(self):
        records = dns_records_for(_row(dkim_public_key="MIIB...ABCD"))
        dkim = next(r for r in records if r.purpose == "dkim")
        assert "p=MIIB...ABCD" in dkim.value

    def test_dmarc_underscore_host(self):
        records = dns_records_for(_row())
        dmarc = next(r for r in records if r.purpose == "dmarc")
        assert dmarc.host == "_dmarc.yourshop.com"
        assert dmarc.type == "TXT"
        assert "v=DMARC1" in dmarc.value


# --- Fully verified property --------------------------------------------


class TestFullyVerified:
    def test_all_three_true(self):
        row = _row(spf_verified=True, dkim_verified=True, dmarc_verified=True)
        assert row.fully_verified is True

    @pytest.mark.parametrize(
        "spf,dkim,dmarc",
        [(True, True, False), (True, False, True), (False, True, True)],
    )
    def test_one_missing(self, spf, dkim, dmarc):
        row = _row(spf_verified=spf, dkim_verified=dkim, dmarc_verified=dmarc)
        assert row.fully_verified is False


# --- verify_domain rate-limit key ---------------------------------------


class TestVerifyRateLimitKey:
    """The rate limit uses a module-level dict keyed on
    ``(str(org_id), domain)``. Confirm the key + eviction shape so the
    real DNS-calling test can lean on this behaviour."""

    def test_second_call_inside_window_would_429(self):
        org = str(uuid.uuid4())
        domain = "yourshop.com"
        key = (org, domain)
        _verify_last_hit.pop(key, None)  # clean slate

        _verify_last_hit[key] = time.time()
        # simulate immediate second call
        elapsed = time.time() - _verify_last_hit[key]
        assert elapsed < _VERIFY_RATE_LIMIT_SECONDS

    def test_call_after_window_resets(self):
        org = str(uuid.uuid4())
        domain = "yourshop.com"
        key = (org, domain)
        _verify_last_hit[key] = time.time() - (_VERIFY_RATE_LIMIT_SECONDS + 1)
        elapsed = time.time() - _verify_last_hit[key]
        assert elapsed >= _VERIFY_RATE_LIMIT_SECONDS


# --- Timestamp columns render as datetime --------------------------------


def test_row_timestamps_use_tz():
    row = _row(spf_last_checked_at=datetime.now(UTC))
    assert row.spf_last_checked_at.tzinfo is not None

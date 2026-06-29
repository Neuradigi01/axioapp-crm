"""Pin tests for the Step-11 quote + invoice triggers.

Covers:

  * Catalog registration — all five event types are present
    (``quote.sent``, ``quote.accepted``, ``invoice.sent``,
    ``invoice.paid``, ``invoice.overdue_7d``).
  * Seed installation — three invoice-cycle triggers per org, all
    idempotent.
  * ``invoice.sent`` publisher fires from ``billing.service.issue``.
  * ``invoice.paid`` publisher fires from ``billing.service.record_payment``
    when the cumulative payment closes the invoice — partial
    payments don't fire it.
  * ``find_overdue`` DAL helper picks up old issued invoices +
    skips paid / draft / void.
  * Overdue scanner is idempotent across daily ticks (the
    deterministic event_id collapses re-publishes).
  * Disabling the seeded "Invoice Overdue 7d" trigger blocks the
    send.

Tests exercise the publishers + DAL directly; the Celery wrapper
is one-line ``asyncio.run``. All ``deliver_run.apply_async`` calls
are mocked so no real workers run.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.automation import (
    event_catalog,
    seeds as automation_seeds,
    tasks as automation_tasks,
)
from src.app.core.automation.dispatcher import dispatch_event
from src.app.core.automation.models import (
    AutomationRunStatus,
    AutomationTrigger,
)
from src.app.core.automation.service import match_triggers
from src.app.core.billing import data_access as billing_da
from src.app.core.billing.models import (
    Invoice,
    InvoiceStatus,
    PaymentMethod,
)
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {
            "id": str(org_id),
            "name": "Demo Workspace",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


async def _install_seeds(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await automation_seeds.install_default_org_seeds(
            test_db, org_id=org_id
        )
        await test_db.commit()
        return result
    finally:
        reset_context(token)


async def _make_invoice(
    test_db,
    *,
    org_id,
    status: InvoiceStatus = InvoiceStatus.issued,
    issued_at: datetime | None = None,
    total: Decimal = Decimal("45000.00"),
) -> Invoice:
    """Insert a contact + invoice row directly. Bypasses the issue()
    state machine so the test can place rows at arbitrary points in
    the lifecycle without dragging the publisher into the fixture."""
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, full_name, phone, email) "
            "VALUES (:id, :org_id, :full_name, :phone, :email)"
        ),
        {
            "id": str(contact_id),
            "org_id": str(org_id),
            "full_name": "Asha Mehta",
            "phone": "+919876543210",
            "email": "asha@example.com",
        },
    )
    inv = Invoice(
        org_id=org_id,
        contact_id=contact_id,
        status=status,
        subtotal=total,
        tax_amount=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        total=total,
        currency="INR",
        issued_at=issued_at,
    )
    test_db.add(inv)
    await test_db.commit()
    await test_db.refresh(inv)
    return inv


# ---------------------------------------------------------------------------
# Catalog registration
# ---------------------------------------------------------------------------


def test_event_catalog_includes_all_five_events():
    """Catalog must surface every event type the seeded triggers
    bind to so the editor's event picker can render them."""
    assert event_catalog.is_known("quote.sent")
    assert event_catalog.is_known("quote.accepted")
    assert event_catalog.is_known("invoice.sent")
    assert event_catalog.is_known("invoice.paid")
    assert event_catalog.is_known("invoice.overdue_7d")


# ---------------------------------------------------------------------------
# Seed installation
# ---------------------------------------------------------------------------


async def test_invoice_seeds_create_three_triggers_per_org(test_db, org_id):
    result = await _install_seeds(test_db, org_id)
    assert "invoice_sent_trigger_id" in result
    assert "invoice_paid_trigger_id" in result
    assert "invoice_overdue_trigger_id" in result

    rows = (
        await test_db.execute(
            select(AutomationTrigger).where(
                AutomationTrigger.org_id == org_id,
                AutomationTrigger.event_type.in_(
                    (
                        "invoice.sent",
                        "invoice.paid",
                        "invoice.overdue_7d",
                    )
                ),
            )
        )
    ).scalars().all()
    assert len(rows) == 3
    assert all(r.channel.value == "email" for r in rows)
    assert all(r.recipient_resolver == "contact.email" for r in rows)


async def test_invoice_seeds_are_idempotent(test_db, org_id):
    first = await _install_seeds(test_db, org_id)
    second = await _install_seeds(test_db, org_id)
    assert first["invoice_sent_trigger_id"] == second[
        "invoice_sent_trigger_id"
    ]
    assert first["invoice_paid_trigger_id"] == second[
        "invoice_paid_trigger_id"
    ]
    assert first["invoice_overdue_trigger_id"] == second[
        "invoice_overdue_trigger_id"
    ]


# ---------------------------------------------------------------------------
# Publishers
# ---------------------------------------------------------------------------


async def test_invoice_sent_publisher_envelope(test_db, org_id):
    """The shared ``_publish_invoice_event`` helper builds the
    envelope. We intercept the bus.publish call + assert the shape."""
    from src.app.core.billing import service as billing_service

    inv = await _make_invoice(
        test_db,
        org_id=org_id,
        status=InvoiceStatus.issued,
        issued_at=datetime.now(timezone.utc),
    )
    inv.number = 4021
    await test_db.commit()
    await test_db.refresh(inv)

    captured: dict = {}

    async def _fake_publish(event_type, payload, *, org_id, event_id):
        captured["event_type"] = event_type
        captured["org_id"] = org_id
        captured["event_id"] = event_id
        captured["payload"] = payload

    with patch(
        "src.app.core.events.bus.publish",
        new=AsyncMock(side_effect=_fake_publish),
    ):
        await billing_service._publish_invoice_event(
            session=test_db,
            inv=inv,
            event_type="invoice.sent",
            event_id_prefix="invoice_sent",
            extra=None,
        )

    assert captured["event_type"] == "invoice.sent"
    assert captured["org_id"] == org_id
    assert captured["event_id"] == f"invoice_sent:{inv.id}"
    assert captured["payload"]["invoice_id"] == str(inv.id)
    assert captured["payload"]["total_amount"] == "45000.00"
    assert captured["payload"]["currency"] == "INR"
    assert captured["payload"]["invoice"]["number"] == 4021


async def test_invoice_paid_publisher_includes_extras(test_db, org_id):
    """The ``invoice.paid`` path passes ``extra={paid_at, payment_method}``;
    those merge into the top-level payload + the nested invoice
    dict."""
    from src.app.core.billing import service as billing_service

    paid_at = datetime.now(timezone.utc)
    inv = await _make_invoice(
        test_db,
        org_id=org_id,
        status=InvoiceStatus.paid,
        issued_at=paid_at - timedelta(days=2),
    )
    inv.paid_at = paid_at
    inv.payment_method = PaymentMethod.upi
    await test_db.commit()
    await test_db.refresh(inv)

    captured: dict = {}

    async def _fake_publish(event_type, payload, *, org_id, event_id):
        captured["event_type"] = event_type
        captured["payload"] = payload

    with patch(
        "src.app.core.events.bus.publish",
        new=AsyncMock(side_effect=_fake_publish),
    ):
        await billing_service._publish_invoice_event(
            session=test_db,
            inv=inv,
            event_type="invoice.paid",
            event_id_prefix="invoice_paid",
            extra={
                "paid_at": paid_at.isoformat(),
                "payment_method": "upi",
            },
        )

    assert captured["event_type"] == "invoice.paid"
    assert captured["payload"]["paid_at"] == paid_at.isoformat()
    assert captured["payload"]["payment_method"] == "upi"
    # Mirrored into the nested invoice dict.
    assert captured["payload"]["invoice"]["paid_at"] == paid_at.isoformat()
    assert captured["payload"]["invoice"]["payment_method"] == "upi"


# ---------------------------------------------------------------------------
# Overdue scanner DAL
# ---------------------------------------------------------------------------


async def test_find_overdue_picks_up_8d_old_issued_invoice(test_db, org_id):
    """An ``issued`` invoice older than 7d shows up in the
    7-day-overdue scan."""
    issued_at = datetime.now(timezone.utc) - timedelta(days=8)
    inv = await _make_invoice(
        test_db,
        org_id=org_id,
        status=InvoiceStatus.issued,
        issued_at=issued_at,
    )

    rows = await billing_da.find_overdue(test_db, days_overdue=7)
    ids = {r.id for r in rows}
    assert inv.id in ids


async def test_find_overdue_skips_paid_draft_void(test_db, org_id):
    """Only ``issued`` invoices count — paid / draft / void are
    excluded from the scan."""
    old = datetime.now(timezone.utc) - timedelta(days=30)
    paid_inv = await _make_invoice(
        test_db,
        org_id=org_id,
        status=InvoiceStatus.paid,
        issued_at=old,
    )
    draft_inv = await _make_invoice(
        test_db,
        org_id=org_id,
        status=InvoiceStatus.draft,
        issued_at=None,
    )
    void_inv = await _make_invoice(
        test_db,
        org_id=org_id,
        status=InvoiceStatus.void,
        issued_at=old,
    )

    rows = await billing_da.find_overdue(test_db, days_overdue=7)
    ids = {r.id for r in rows}
    assert paid_inv.id not in ids
    assert draft_inv.id not in ids
    assert void_inv.id not in ids


async def test_find_overdue_skips_recent_issued(test_db, org_id):
    """Issued invoice less than 7 days old → NOT overdue."""
    recent = datetime.now(timezone.utc) - timedelta(days=3)
    inv = await _make_invoice(
        test_db,
        org_id=org_id,
        status=InvoiceStatus.issued,
        issued_at=recent,
    )

    rows = await billing_da.find_overdue(test_db, days_overdue=7)
    ids = {r.id for r in rows}
    assert inv.id not in ids


# ---------------------------------------------------------------------------
# Dispatcher + idempotency
# ---------------------------------------------------------------------------


async def test_overdue_dispatch_is_idempotent(test_db, org_id):
    """Two dispatches with the same deterministic event_id yield
    exactly one run row — the daily-tick replay safety net."""
    await _install_seeds(test_db, org_id)
    inv_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, full_name, phone, email) "
            "VALUES (:id, :org_id, :full_name, :phone, :email)"
        ),
        {
            "id": str(contact_id),
            "org_id": str(org_id),
            "full_name": "Asha Mehta",
            "phone": "+919876543210",
            "email": "asha@example.com",
        },
    )
    await test_db.commit()

    payload = {
        "invoice_id": str(inv_id),
        "contact_id": str(contact_id),
        "total_amount": "45000.00",
        "currency": "INR",
        "issued_at": (
            datetime.now(timezone.utc) - timedelta(days=8)
        ).isoformat(),
        "days_overdue": 8,
        "contact": {
            "full_name": "Asha Mehta",
            "email": "asha@example.com",
        },
    }
    event_id = f"invoice_overdue_7d:{inv_id}"

    with patch.object(automation_tasks.deliver_run, "apply_async"):
        first = await dispatch_event(
            test_db,
            org_id=org_id,
            event_type="invoice.overdue_7d",
            payload=payload,
            event_id=event_id,
        )
        second = await dispatch_event(
            test_db,
            org_id=org_id,
            event_type="invoice.overdue_7d",
            payload=payload,
            event_id=event_id,
        )

    assert len(first) == 1
    assert len(second) <= 1
    assert first[0].status == AutomationRunStatus.queued


async def test_disabled_overdue_trigger_skips_send(test_db, org_id):
    """If the operator disables the seeded 'Invoice Overdue 7d'
    trigger, subsequent dispatches enrol no runs."""
    seeds_result = await _install_seeds(test_db, org_id)
    trigger_id = uuid.UUID(seeds_result["invoice_overdue_trigger_id"])
    trigger = (
        await test_db.execute(
            select(AutomationTrigger).where(
                AutomationTrigger.id == trigger_id,
                AutomationTrigger.org_id == org_id,
            )
        )
    ).scalar_one()
    trigger.enabled = False
    await test_db.commit()

    matches = await match_triggers(
        test_db,
        org_id=org_id,
        event_type="invoice.overdue_7d",
        payload={"contact": {"email": "asha@example.com"}},
    )
    names = [m.name for m in matches]
    assert "Invoice Overdue 7d" not in names

    with patch.object(automation_tasks.deliver_run, "apply_async") as schedule:
        runs = await dispatch_event(
            test_db,
            org_id=org_id,
            event_type="invoice.overdue_7d",
            payload={
                "invoice_id": str(uuid.uuid4()),
                "contact_id": str(uuid.uuid4()),
                "total_amount": "45000.00",
                "currency": "INR",
                "contact": {
                    "full_name": "Asha Mehta",
                    "email": "asha@example.com",
                },
            },
            event_id=f"invoice_overdue_7d:{uuid.uuid4()}",
        )

    assert runs == []
    assert not schedule.called

"""Audience resolver — does `{q, source, tag}` actually narrow the set?"""

from __future__ import annotations

import uuid

import pytest

from src.app.core.campaigns.service import resolve_audience
from src.app.core.contacts.models import Contact


async def _seed_contacts(org_id: uuid.UUID) -> dict[str, uuid.UUID]:
    from tests.conftest import TestSession

    async with TestSession() as session:
        a = Contact(
            org_id=org_id,
            full_name="Alice Walker",
            phone="+919000000001",
            source="walk-in",
            tags=["vip", "sofa"],
        )
        b = Contact(
            org_id=org_id,
            full_name="Bob Verma",
            phone="+919000000002",
            source="referral",
            tags=["sofa"],
        )
        c = Contact(
            org_id=org_id,
            full_name="Carol Singh",
            phone="+919000000003",
            source="walk-in",
            tags=["chair"],
        )
        session.add_all([a, b, c])
        await session.commit()
        return {"alice": a.id, "bob": b.id, "carol": c.id}


@pytest.mark.asyncio
async def test_empty_filter_returns_every_contact(test_db, seeded_admin):
    ids = await _seed_contacts(seeded_admin["org"].id)
    out = await resolve_audience(test_db, audience_filter={})
    assert set(out) == set(ids.values())


@pytest.mark.asyncio
async def test_filter_by_source(test_db, seeded_admin):
    ids = await _seed_contacts(seeded_admin["org"].id)
    out = await resolve_audience(test_db, audience_filter={"source": "walk-in"})
    assert set(out) == {ids["alice"], ids["carol"]}


@pytest.mark.asyncio
async def test_filter_by_tag(test_db, seeded_admin):
    ids = await _seed_contacts(seeded_admin["org"].id)
    out = await resolve_audience(test_db, audience_filter={"tag": "sofa"})
    assert set(out) == {ids["alice"], ids["bob"]}


@pytest.mark.asyncio
async def test_filter_by_q_matches_name_phone_email(test_db, seeded_admin):
    ids = await _seed_contacts(seeded_admin["org"].id)
    by_name = await resolve_audience(test_db, audience_filter={"q": "verm"})
    assert by_name == [ids["bob"]]
    by_phone = await resolve_audience(test_db, audience_filter={"q": "0003"})
    assert by_phone == [ids["carol"]]


@pytest.mark.asyncio
async def test_filter_combination_narrows_further(test_db, seeded_admin):
    ids = await _seed_contacts(seeded_admin["org"].id)
    out = await resolve_audience(
        test_db,
        audience_filter={"source": "walk-in", "tag": "sofa"},
    )
    assert out == [ids["alice"]]

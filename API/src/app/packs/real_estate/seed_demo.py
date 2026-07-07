"""Real Estate pack demo-seed script.

Idempotently inserts a curated set of 5 sample properties into the
given org so the Properties list, gallery, publish flow, and public
pages all have realistic data to demo.

  docker exec crm-api-1 python -m src.app.packs.real_estate.seed_demo \
      --org <org-slug>

For each property in `sample_properties.json`:
  1. Skip if a row with the same (org_id, title) already exists — the
     script is safe to re-run.
  2. Insert via the module's service layer so the state machine,
     slug generation, and audit hooks all fire.
  3. Generate two placeholder JPEG images in-process (Pillow), one
     landscape "hero" and one portrait "detail", each stamped with
     the property label and a corner tag. Uploaded through
     `upload_property_images` so validation + storage + featured
     bookkeeping all match the runtime path.
  4. If `publish=True` in the JSON, publish the row via the service
     so `published_at` gets set correctly.

No binary assets ship in the repo — every image is generated fresh
each run from a deterministic (color + label) tuple in the JSON.
Rerunning after tweaking the JSON updates the sample gallery
without needing to delete anything.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from src.app.core.tenants import data_access as tenants_da
from src.app.core.users.models import OrganizationMember
from src.app.packs.real_estate.modules.property import data_access as prop_da
from src.app.packs.real_estate.modules.property import service as prop_svc
from src.app.packs.real_estate.modules.property.schemas import PropertyCreate
from src.app.shared.db import async_session

logger = logging.getLogger("real_estate.seed_demo")

_SAMPLE_JSON = Path(__file__).parent / "sample_properties.json"


def _make_image(color: tuple[int, int, int], label: str, tag: str, size=(1200, 800)) -> bytes:
    """Generate a deterministic JPEG stamped with the property label
    and a corner tag ("Hero" / "Detail"). Uses Pillow's default
    bitmap font so no external font asset is required."""
    img = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(img)
    try:
        big = ImageFont.load_default(size=64)
        small = ImageFont.load_default(size=28)
    except Exception:
        # Older Pillow versions don't accept `size` — fall back.
        big = ImageFont.load_default()
        small = ImageFont.load_default()
    # Center label.
    bbox = draw.textbbox((0, 0), label, font=big)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        ((size[0] - tw) / 2, (size[1] - th) / 2),
        label,
        font=big,
        fill=(255, 255, 255),
    )
    # Corner tag.
    draw.rectangle((0, 0, 200, 50), fill=(0, 0, 0))
    draw.text((16, 12), tag, font=small, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return buf.getvalue()


async def _seed_one(
    session,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    row: dict[str, Any],
) -> tuple[str, str]:
    """Insert (or skip) one sample. Returns (title, action) for the
    summary log — action is 'skipped' when the row already exists,
    otherwise 'created:draft' or 'created:published'."""
    existing_all, _total = await prop_da.list_properties(
        session,
        search=row["title"],
        page=1,
        size=1,
    )
    matched = [p for p in existing_all if p.org_id == org_id and p.title == row["title"]]
    if matched:
        return row["title"], "skipped"

    payload = PropertyCreate.model_validate(
        {k: v for k, v in row.items() if k not in {"publish", "image_color", "image_label"}}
    )
    created = await prop_svc.create_property(
        session,
        org_id=org_id,
        actor_user_id=actor_user_id,
        payload=payload,
    )

    label: str = row["image_label"]
    color = tuple(row["image_color"])
    hero = _make_image(color, label, "Hero", size=(1200, 800))
    detail = _make_image(color, label, "Detail", size=(900, 1200))
    await prop_svc.upload_property_images(
        session,
        org_id=org_id,
        property_id=created.id,
        files=[
            (f"{label.replace(' ', '_')}_hero.jpg", hero, "image/jpeg"),
            (f"{label.replace(' ', '_')}_detail.jpg", detail, "image/jpeg"),
        ],
    )

    if row.get("publish"):
        await prop_svc.publish_property(session, org_id=org_id, property_id=created.id)
        return created.title, "created:published"
    return created.title, "created:draft"


async def _resolve_owner_uuid(session, org_id: uuid.UUID) -> uuid.UUID | None:
    """Pick any active member of the org for `owner_id`. Prefers the
    lowest-id member (typically the founding user)."""
    from src.app.core.users.models import User

    stmt = (
        select(User.legacy_uuid)
        .join(OrganizationMember, OrganizationMember.user_member_id == User.id)
        .where(OrganizationMember.organization_id == org_id)
        .where(OrganizationMember.is_active.is_(True))
        .order_by(OrganizationMember.id.asc())
        .limit(1)
    )
    result = (await session.execute(stmt)).scalar_one_or_none()
    return result


async def run(org_slug: str) -> int:
    async with async_session() as session:
        org = await tenants_da.get_organization_by_slug(session, org_slug)
        if org is None:
            print(f"[seed_demo] org with slug '{org_slug}' not found", file=sys.stderr)
            return 2

        owner_uuid = await _resolve_owner_uuid(session, org.id)
        if owner_uuid is None:
            print(
                f"[seed_demo] org '{org_slug}' has no active members — cannot pick an owner",
                file=sys.stderr,
            )
            return 3

        rows = json.loads(_SAMPLE_JSON.read_text(encoding="utf-8"))
        print(f"[seed_demo] target org: {org.name} ({org.id})")
        print(f"[seed_demo] acting as user_uuid: {owner_uuid}")
        print(f"[seed_demo] loaded {len(rows)} sample rows from {_SAMPLE_JSON.name}")

        summary: list[tuple[str, str]] = []
        for row in rows:
            try:
                summary.append(
                    await _seed_one(
                        session,
                        org_id=org.id,
                        actor_user_id=owner_uuid,
                        row=row,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — never abort the sweep
                logger.exception("row failed: %s", row.get("title"))
                summary.append((row.get("title", "<unknown>"), f"error: {exc}"))

        print("[seed_demo] summary:")
        for title, action in summary:
            print(f"  - {action:20s} {title}")
        return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Seed the Real Estate pack demo dataset.")
    parser.add_argument("--org", required=True, help="Target organization slug.")
    args = parser.parse_args()
    return asyncio.run(run(args.org))


if __name__ == "__main__":
    sys.exit(main())

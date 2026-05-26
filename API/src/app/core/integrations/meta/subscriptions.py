"""Read + write helpers around Meta Pages and Lead-Form subscriptions.

Four operations, all thin wrappers around `MetaGraphClient`:

  - `list_pages(client)` — `GET /me/accounts`. Returns every Page the
    OAuth user manages. Backs the Settings UI's Page picker. Each
    page comes back with its own `access_token` (the Page token); we
    don't persist these, callers re-fetch every time they need to act
    on a Page.

  - `list_lead_forms_for_page(client, page_id, page_token)` —
    `GET /{page_id}/leadgen_forms`. Lists the Lead Forms attached to
    that Page. Status filter for ACTIVE forms only.

  - `subscribe_page(client, page_id, page_token)` —
    `POST /{page_id}/subscribed_apps` with `subscribed_fields=leadgen`.
    After this returns 200, Meta starts delivering lead events to our
    webhook URL (configured ONCE per environment in the Meta app
    dashboard, NOT per integration — that's how Meta's webhook model
    works).

  - `unsubscribe_page(client, page_id, page_token)` — symmetric
    `DELETE /{page_id}/subscribed_apps`. Stops deliveries for that
    Page. Doesn't touch other Pages on the same integration.

Both Facebook and Instagram Lead Ads ride the same `leadgen` webhook
field, so there's no parallel Instagram code path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.app.core.integrations.meta.api_client import MetaGraphClient


@dataclass(frozen=True, slots=True)
class MetaPage:
    """One entry from `/me/accounts`. `access_token` is the per-Page
    token derived from the user token — needed for every subsequent
    Page-scoped call (list forms, subscribe, unsubscribe)."""

    page_id: str
    name: str
    access_token: str
    category: Optional[str] = None


@dataclass(frozen=True, slots=True)
class MetaLeadForm:
    """One entry from `/{page_id}/leadgen_forms`. `status` is
    typically `ACTIVE` or `ARCHIVED` — Owner pickers should default
    to filtering out archived forms but we don't enforce it here."""

    form_id: str
    name: str
    status: str
    page_id: str


async def list_pages(client: MetaGraphClient) -> list[MetaPage]:
    """Every Page the OAuth user manages. Usually 1-5 for a small
    retailer; can be 100+ for a multi-brand operator (Business Manager).

    Pagination: Meta returns `paging.next` for >25 results. v1 takes
    the first page only — picker UI will show "showing first 25, use
    Business Manager to refine if more". When orgs hit this, we add
    cursor iteration in a follow-up small task.
    """
    body = await client.get(
        "/me/accounts",
        params={"fields": "id,name,access_token,category"},
    )
    raw = body.get("data") or []
    pages: list[MetaPage] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        page_id = item.get("id")
        token = item.get("access_token")
        name = item.get("name")
        if not page_id or not token or not name:
            continue
        pages.append(
            MetaPage(
                page_id=str(page_id),
                name=str(name),
                access_token=str(token),
                category=item.get("category"),
            )
        )
    return pages


async def list_lead_forms_for_page(
    client: MetaGraphClient,
    *,
    page_id: str,
    page_token: str,
) -> list[MetaLeadForm]:
    """Lead Forms on a single Page. `page_token` is the Page-scoped
    access_token from `list_pages` (NOT the user token) — Meta
    requires it for this endpoint."""
    body = await client.get(
        f"/{page_id}/leadgen_forms",
        params={"fields": "id,name,status"},
        access_token=page_token,
    )
    raw = body.get("data") or []
    forms: list[MetaLeadForm] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        form_id = item.get("id")
        if not form_id:
            continue
        forms.append(
            MetaLeadForm(
                form_id=str(form_id),
                name=str(item.get("name") or ""),
                status=str(item.get("status") or "UNKNOWN"),
                page_id=page_id,
            )
        )
    return forms


async def subscribe_page(
    client: MetaGraphClient,
    *,
    page_id: str,
    page_token: str,
) -> bool:
    """POST `/{page_id}/subscribed_apps` with `subscribed_fields=
    leadgen`. After this returns 200, Meta delivers lead events on
    every Lead Form attached to this Page to our webhook.

    Returns True on Meta's `{"success": true}` response."""
    body = await client.post(
        f"/{page_id}/subscribed_apps",
        params={"subscribed_fields": "leadgen"},
        access_token=page_token,
    )
    return bool(body.get("success"))


async def unsubscribe_page(
    client: MetaGraphClient,
    *,
    page_id: str,
    page_token: str,
) -> bool:
    """DELETE `/{page_id}/subscribed_apps`. Removes the leadgen
    subscription for this Page; deliveries stop within Meta's normal
    propagation window (a few seconds).

    Returns True on Meta's `{"success": true}` response."""
    body = await client.delete(
        f"/{page_id}/subscribed_apps",
        access_token=page_token,
    )
    return bool(body.get("success"))


async def find_page_token(
    client: MetaGraphClient,
    *,
    page_id: str,
) -> Optional[str]:
    """Look up the access_token for a specific page id by paging
    through `/me/accounts`. Returns None if the user no longer
    manages that page (could happen if Pages were transferred out of
    their account between subscribe and a follow-up call).

    Used by router endpoints that take a `page_id` path param — the
    Owner clicked "subscribe to Page X"; we need X's token to act."""
    pages = await list_pages(client)
    for page in pages:
        if page.page_id == page_id:
            return page.access_token
    return None


__all__ = [
    "MetaLeadForm",
    "MetaPage",
    "find_page_token",
    "list_lead_forms_for_page",
    "list_pages",
    "subscribe_page",
    "unsubscribe_page",
]

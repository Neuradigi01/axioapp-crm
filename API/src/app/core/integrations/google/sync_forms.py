"""Discovery surface for the Google Ads connection — list accessible
ad accounts (customer IDs) + their lead forms. Drives the Settings UI
picker in Step 7 ("which forms feed the CRM?").

Two functions:

  - `list_accessible_accounts(client)` — GET on
    `customers:listAccessibleCustomers`. Returns the list of customer
    resource names the connected Google identity has any access to.
    No login-customer-id required.
  - `list_lead_forms(client, customer_id)` — GAQL search via
    `googleAds:searchStream` against the `asset` resource filtered to
    `LEAD_FORM` type assets. Returns parsed forms with id + label.

We use ASSET (the modern object in v15+) rather than the older
`extension_feed_item.LEAD_FORM` (deprecated). Both data sources
return the same forms; ASSET is what Google recommends + what
matches the UI you see in the Google Ads dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.app.core.integrations.google.api_client import GoogleAdsRestClient


@dataclass(frozen=True, slots=True)
class GoogleAdsAccount:
    """One entry in `customers:listAccessibleCustomers`. The
    `customer_id` is the 10-digit Google Ads account number with
    hyphens stripped (matches what the API expects in subsequent
    requests' `login-customer-id` header)."""

    customer_id: str
    resource_name: str  # full "customers/<id>" form, for debugging


@dataclass(frozen=True, slots=True)
class GoogleLeadForm:
    """One Lead Form asset on a given customer. `form_id` is the
    asset resource id (last segment of `asset.resource_name`)."""

    form_id: str
    name: Optional[str]
    resource_name: str


async def list_accessible_accounts(
    client: GoogleAdsRestClient,
) -> list[GoogleAdsAccount]:
    """Every Google Ads customer the connected identity can see.
    Usually 1 (a single ad account) but can be many if the identity
    is on a Manager (MCC) account.
    """
    body = await client.get("customers:listAccessibleCustomers")
    resource_names = body.get("resourceNames", []) or []
    accounts: list[GoogleAdsAccount] = []
    for rn in resource_names:
        # rn looks like "customers/1234567890"
        if not rn.startswith("customers/"):
            continue
        accounts.append(
            GoogleAdsAccount(
                customer_id=rn.split("/", 1)[1],
                resource_name=rn,
            )
        )
    return accounts


# GAQL — pull every LEAD_FORM asset on the customer. v17 returns this
# as the asset's `lead_form_asset` block; we just need the name + id
# for the picker UI in Step 7. Field mapping (Step 8) drills into the
# form's individual question fields via a follow-up query.
_LEAD_FORM_QUERY = (
    "SELECT asset.id, asset.name, asset.resource_name "
    "FROM asset "
    "WHERE asset.type = 'LEAD_FORM'"
)


async def list_lead_forms(
    client: GoogleAdsRestClient, *, customer_id: str
) -> list[GoogleLeadForm]:
    """Every Lead Form asset on the given customer. `customer_id`
    must NOT carry hyphens — the API expects the raw 10-digit id.
    Callers strip hyphens before passing in."""
    body = await client.post(
        f"customers/{customer_id}/googleAds:searchStream",
        json={"query": _LEAD_FORM_QUERY},
        login_customer_id=customer_id,
    )
    # `searchStream` returns either a single batch dict OR an array of
    # batches depending on result-set size. Normalise.
    if isinstance(body, list):
        batches = body
    else:
        batches = [body]

    forms: list[GoogleLeadForm] = []
    for batch in batches:
        for row in batch.get("results", []) or []:
            asset = row.get("asset", {})
            asset_id = str(asset.get("id", "")) if asset.get("id") else None
            if not asset_id:
                continue
            forms.append(
                GoogleLeadForm(
                    form_id=asset_id,
                    name=asset.get("name"),
                    resource_name=asset.get(
                        "resourceName", f"customers/{customer_id}/assets/{asset_id}"
                    ),
                )
            )
    return forms


__all__ = [
    "GoogleAdsAccount",
    "GoogleLeadForm",
    "list_accessible_accounts",
    "list_lead_forms",
]

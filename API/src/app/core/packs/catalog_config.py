"""Static catalog of pack tiles for the onboarding picker.

Lists every CRM template the onboarding page shows as a selectable or
"Coming soon" tile. A tile is rendered selectable (`status="available"`)
when its `pack_id` matches an installable pack on disk
(`src/app/packs/<id>/pack.yaml`). Otherwise it is rendered with a
"Coming soon" badge and is rejected by the onboarding endpoint.

To add a new vertical placeholder: append one dict to `CATALOG_PACKS`
with the next available `display_order` (in increments of 100). No
code change elsewhere.

When a placeholder pack is fully built (manifest + installer + modules
+ UI), its `pack.yaml` is auto-discovered and the same entry here
flips to `status="available"` — no edit required.
"""
from __future__ import annotations

from typing import Final, TypedDict


class CatalogTileConfig(TypedDict):
    pack_id: str
    name: str
    description: str
    icon: str
    default_currency: str
    default_tax_rate: float
    modules_preview: list[str]
    display_order: int


CATALOG_PACKS: Final[list[CatalogTileConfig]] = [
    {
        "pack_id": "base",
        "name": "Core CRM",
        "description": (
            "Universal CRM for any business — contacts, leads, "
            "pipelines, tasks, billing."
        ),
        "icon": "briefcase",
        "default_currency": "INR",
        "default_tax_rate": 18.0,
        "modules_preview": [
            "contacts",
            "leads",
            "pipelines",
            "tasks",
            "billing",
        ],
        "display_order": 0,
    },
    {
        "pack_id": "furniture",
        "name": "Furniture CRM",
        "description": (
            "Built for furniture retail — inventory, custom orders, "
            "field ops, POS billing."
        ),
        "icon": "armchair",
        "default_currency": "INR",
        "default_tax_rate": 18.0,
        "modules_preview": [
            "inventory",
            "custom_orders",
            "field_ops",
            "billing",
        ],
        "display_order": 100,
    },
    {
        "pack_id": "real_estate",
        "name": "Real Estate CRM",
        "description": (
            "Site visits, RERA tracking, channel partners, brokerage."
        ),
        "icon": "home",
        "default_currency": "INR",
        "default_tax_rate": 5.0,
        "modules_preview": [
            "listings",
            "site_visits",
            "channel_partners",
            "brokerage",
        ],
        "display_order": 200,
    },
    {
        "pack_id": "clinic",
        "name": "Clinic / Dental CRM",
        "description": (
            "Patient records, appointments, treatment plans, recalls."
        ),
        "icon": "heart-pulse",
        "default_currency": "INR",
        "default_tax_rate": 0.0,
        "modules_preview": [
            "patients",
            "appointments",
            "treatment_plans",
            "recalls",
        ],
        "display_order": 300,
    },
    {
        "pack_id": "sales",
        "name": "Sales CRM",
        "description": (
            "Generic B2B sales — deals, quotes, forecasting, territory."
        ),
        "icon": "trending-up",
        "default_currency": "INR",
        "default_tax_rate": 18.0,
        "modules_preview": [
            "deals",
            "quotes",
            "forecasting",
            "territory",
        ],
        "display_order": 400,
    },
    {
        "pack_id": "automotive",
        "name": "Automotive CRM",
        "description": (
            "Dealerships and service centers — test drives, service, AMC."
        ),
        "icon": "car",
        "default_currency": "INR",
        "default_tax_rate": 28.0,
        "modules_preview": [
            "inventory",
            "test_drives",
            "service_bookings",
            "amc",
        ],
        "display_order": 500,
    },
    {
        "pack_id": "salon",
        "name": "Salon & Spa CRM",
        "description": "Stylist bookings, packages, loyalty points, retail.",
        "icon": "scissors",
        "default_currency": "INR",
        "default_tax_rate": 18.0,
        "modules_preview": [
            "bookings",
            "stylists",
            "packages",
            "loyalty",
        ],
        "display_order": 600,
    },
    {
        "pack_id": "fitness",
        "name": "Fitness CRM",
        "description": (
            "Gym memberships, trainer schedules, attendance, diet plans."
        ),
        "icon": "dumbbell",
        "default_currency": "INR",
        "default_tax_rate": 18.0,
        "modules_preview": [
            "memberships",
            "trainers",
            "attendance",
            "diet_plans",
        ],
        "display_order": 700,
    },
    {
        "pack_id": "education",
        "name": "Education CRM",
        "description": (
            "Coaching and schools — admissions, batches, fees, parent comms."
        ),
        "icon": "graduation-cap",
        "default_currency": "INR",
        "default_tax_rate": 0.0,
        "modules_preview": [
            "admissions",
            "batches",
            "fees",
            "parent_comms",
        ],
        "display_order": 800,
    },
    {
        "pack_id": "hospitality",
        "name": "Hospitality CRM",
        "description": (
            "Hotels and restaurants — reservations, guests, loyalty, feedback."
        ),
        "icon": "utensils",
        "default_currency": "INR",
        "default_tax_rate": 18.0,
        "modules_preview": [
            "reservations",
            "guests",
            "loyalty",
            "feedback",
        ],
        "display_order": 900,
    },
]


__all__ = ["CATALOG_PACKS", "CatalogTileConfig"]

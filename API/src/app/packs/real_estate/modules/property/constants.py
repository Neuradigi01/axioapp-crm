"""Property module — string enums for status, type, category.

Kept as plain Python string enums (not Postgres ENUM types). The DB
columns are plain `VARCHAR` — schema evolutions (adding a new
property_type, a new category, a "reserved" status) are one-line
Python changes, not `ALTER TYPE ... ADD VALUE` migrations. The service
layer validates every write against these enums; the DAL treats the
column as an opaque string.
"""

from __future__ import annotations

import enum


class PropertyStatus(str, enum.Enum):
    """Lifecycle state of a property listing.

    Transitions are enforced in `service.py`. `draft` is the default on
    insert. `published` requires at least one image. `archived` and
    `sold` are terminal (owner can unarchive → draft; sold stays sold).
    """

    draft = "draft"
    published = "published"
    unpublished = "unpublished"
    archived = "archived"
    sold = "sold"


class PropertyType(str, enum.Enum):
    """Physical asset class. Matches the front-end type dropdown."""

    apartment = "apartment"
    villa = "villa"
    plot = "plot"
    commercial_office = "commercial_office"
    commercial_shop = "commercial_shop"
    warehouse = "warehouse"
    farmhouse = "farmhouse"
    pg_hostel = "pg_hostel"
    other = "other"


class PropertyCategory(str, enum.Enum):
    """Sale vs rent × residential/commercial/land. Drives what price
    field the front-end shows (rent shows /mo, sale shows outright).
    """

    residential_sale = "residential_sale"
    residential_rent = "residential_rent"
    commercial_sale = "commercial_sale"
    commercial_rent = "commercial_rent"
    land_sale = "land_sale"


__all__ = ["PropertyCategory", "PropertyStatus", "PropertyType"]

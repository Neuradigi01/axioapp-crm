"""Data-access layer for the campaigns module.

Per-module ``data_access/`` folder per the project convention. Pure
query helpers, no transactions, no audit. Leaf — never imports a
service.py.

Sub-modules:

  - :mod:`templates` — Step-11 helpers for loading the central
    template row + (for WhatsApp campaigns) the matching extension
    row in one round-trip.
"""
from src.app.core.campaigns.data_access.templates import (
    get_wa_extension_for_campaign_template,
)


__all__ = ["get_wa_extension_for_campaign_template"]

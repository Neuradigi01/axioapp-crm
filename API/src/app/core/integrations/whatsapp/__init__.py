"""WhatsApp Business Cloud API integration — per-org credential storage,
connect/disconnect/test surface, and (from Step 3.5.4) template sync.

Architecture mirrors `integrations/google/` and `integrations/meta/`:
the per-`(org, provider)` Integration row in the parent table holds
the bearer token + lifecycle status, and this subpackage's
`WhatsAppAccountConfig` sidecar holds WA-specific fields (phone_id,
waba_id, app_secret, verify_token, display_phone_number) that don't
fit the generic OAuth shape.

Public re-exports keep the service surface small for callers in other
modules — the campaigns dispatch (Step 3.5.3+) and template sync
(Step 3.5.4) both go through `connect.get_active_config`.
"""
from src.app.core.integrations.whatsapp.connect import (
    connect_account,
    disconnect_account,
    get_active_config,
    get_status,
    test_connection,
)

__all__ = [
    "connect_account",
    "disconnect_account",
    "get_active_config",
    "get_status",
    "test_connection",
]

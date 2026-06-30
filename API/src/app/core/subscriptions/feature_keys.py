"""Typed constants for every feature key declared in ``plans.yaml``.

Call sites pass these constants to ``requires_feature`` instead of
hard-coded strings so typos are caught at import time rather than at
runtime as a silent 402 mis-route::

    from src.app.core.subscriptions.feature_keys import (
        FEATURE_AUTOMATION_WORKFLOWS,
    )

    @router.post("/automation/workflows")
    @requires_feature(FEATURE_AUTOMATION_WORKFLOWS)
    async def create_workflow(...): ...

The constants are kept in lock-step with ``plans.yaml`` via the mutual
check in ``tests/test_subscriptions_feature_keys.py``:

  - every ``FEATURE_*`` constant must match a key in ``KNOWN_FEATURE_KEYS``
  - every key in ``KNOWN_FEATURE_KEYS`` must have a ``FEATURE_*`` constant

Either direction failing is a developer bug — fix the YAML, the registry
set, and this module together.
"""

from __future__ import annotations

# ----- Core CRM read/write surfaces (granted on every plan, trial+) --------
FEATURE_CONTACTS_READ: str = "contacts.read"
FEATURE_CONTACTS_WRITE: str = "contacts.write"
FEATURE_LEADS_MANUAL_ENTRY: str = "leads.manual_entry"
FEATURE_TASKS_READ: str = "tasks.read"
FEATURE_TASKS_WRITE: str = "tasks.write"
FEATURE_WALKINS_READ: str = "walkins.read"
FEATURE_PIPELINES_READ: str = "pipelines.read"

# ----- Standard-tier features ----------------------------------------------
FEATURE_AUTOMATION_WORKFLOWS: str = "automation.workflows"
FEATURE_CONVERSATIONS_UNIFIED_INBOX: str = "conversations.unified_inbox"
FEATURE_INTEGRATIONS_WHATSAPP: str = "integrations.whatsapp"
FEATURE_INTEGRATIONS_EMAIL_IMAP_SMTP: str = "integrations.email_imap_smtp"
FEATURE_ADS_GOOGLE_WEBHOOK: str = "ads.google_webhook"
FEATURE_ADS_META_WEBHOOK: str = "ads.meta_webhook"
FEATURE_CALLS_RECORDING: str = "calls.recording"
FEATURE_CAMPAIGNS_EMAIL: str = "campaigns.email"

# ----- Enterprise-tier features --------------------------------------------
FEATURE_SSO_SAML: str = "sso.saml"
FEATURE_AUDIT_FULL_LOG: str = "audit.full_log"
FEATURE_MULTI_BRANCH: str = "multi_branch"
FEATURE_WHITE_LABEL: str = "white_label"


__all__ = [
    "FEATURE_CONTACTS_READ",
    "FEATURE_CONTACTS_WRITE",
    "FEATURE_LEADS_MANUAL_ENTRY",
    "FEATURE_TASKS_READ",
    "FEATURE_TASKS_WRITE",
    "FEATURE_WALKINS_READ",
    "FEATURE_PIPELINES_READ",
    "FEATURE_AUTOMATION_WORKFLOWS",
    "FEATURE_CONVERSATIONS_UNIFIED_INBOX",
    "FEATURE_INTEGRATIONS_WHATSAPP",
    "FEATURE_INTEGRATIONS_EMAIL_IMAP_SMTP",
    "FEATURE_ADS_GOOGLE_WEBHOOK",
    "FEATURE_ADS_META_WEBHOOK",
    "FEATURE_CALLS_RECORDING",
    "FEATURE_CAMPAIGNS_EMAIL",
    "FEATURE_SSO_SAML",
    "FEATURE_AUDIT_FULL_LOG",
    "FEATURE_MULTI_BRANCH",
    "FEATURE_WHITE_LABEL",
]

"""Mailgun inbound-email receiving sub-module.

Sibling to ``core/email/gmail/`` and ``core/email/microsoft/``. Ships
the webhook endpoint, signature verification, ingest task, DLQ
bookkeeping, and orphan cleanup for the manual-SMTP-sender reply
capture flow. Gmail and Microsoft OAuth mailboxes are handled by
their own sub-modules and are NOT touched by this one — memory
``project_mailgun_inbound_scope.md`` locks that scope.

Files land per the layered convention as the track progresses
(Steps 3–5): ``router.py``, ``service.py``, ``data_access.py``,
``schemas.py``, ``tasks.py``, ``orphan_cleanup.py``,
``pending_inbound_sweeper.py``. This ``__init__`` re-exports the
DLQ model so ``import core.email.mailgun`` registers it in
``Base.metadata`` for ``create_all`` (tests) + Alembic autogenerate.
"""

from src.app.core.email.mailgun.dlq_models import EmailInboundDlq  # noqa: F401

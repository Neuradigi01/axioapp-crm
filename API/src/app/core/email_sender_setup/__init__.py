"""Email sender setup module — SPF / DKIM / DMARC verification per domain.

Campaigns v1 Step 07 (backend, 07a). Ships:

  * :class:`models.EmailSenderDomain` — one row per verified/pending
    domain per org.
  * :mod:`service` — domain create + verification (reuses
    :mod:`core.email.dkim_spf_check` which runs the three DNS
    lookups in parallel).
  * :mod:`router` — the ``/api/v1/email-sender-setup/*`` endpoints.

Frontend page ships in 07b (deferred). The pre-flight enforcement
in :mod:`core.campaigns.service.enqueue` lands here so ``run.cmd
upgrade`` alone is enough for the compliance behaviour to kick in.
"""

from src.app.core.email_sender_setup.router import router

__all__ = ["router"]

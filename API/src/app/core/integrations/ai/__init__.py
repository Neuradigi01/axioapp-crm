"""BYOK provider-key store for AI Assistants.

Sub-module of :mod:`core.integrations` — mirrors the "connect an
external account" pattern used by ``core/integrations/google`` /
``meta`` / ``whatsapp`` / ``google_calendar`` etc., but for
per-org LLM API keys the assistants module (Step 5 onward) reads
by ``key_id`` when calling ``shared.llm.factory(...)``.

Concept map:

  * :class:`~core.integrations.ai.models.AiProviderKey` — one row
    per stored OpenAI key. Ciphertext is AES-GCM; AAD binds it to
    ``(org_id, key_id, key_version)`` so a raw-SQL insider cannot
    copy row A's ciphertext into row B and cause org B's traffic
    to be billed against org A's OpenAI account (Attacker review
    finding C3, folded into the plan).

  * :class:`~core.integrations.ai.models.OrgAiCostBudget` — one row
    per org (UNIQUE). Daily/monthly USD caps + running spent
    counters. The chat runtime (Step 9) calls
    :func:`~core.integrations.ai.service.charge_budget` before every
    LLM call to short-circuit when a cap would be exceeded — v1
    BYOK product means the org pays OpenAI directly, so a per-org
    hard cap is a launch-blocker (Attacker review C5).

The Fernet wrapper in ``core/integrations/crypto.py`` is intentionally
NOT reused: Fernet has no AAD slot, and sharing an encryption key
across multiple secret classes means one leak decrypts everything.
See :mod:`core.integrations.ai.crypto` for the AES-GCM/AAD wrapper.
"""

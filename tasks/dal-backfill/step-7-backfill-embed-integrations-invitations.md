# Step 7 — Backfill DAL (embed, integrations, invitations)

**Goal:** Create `data_access.py` in three core modules. Move all SQL/ORM out of `service.py`. Behaviour unchanged.
**Status:** COMPLETED
**Depends on:** Step 6.

---

## Scope

In-scope:
- `core/embed/data_access.py` — **NEW**
- `core/integrations/data_access.py` — **NEW** (the parent integrations module, NOT `integrations/whatsapp` which is its own module with DAL flattened in Step 3)
- `core/invitations/data_access.py` — **NEW**
- Corresponding `service.py` updates.

Out of scope: behaviour changes.

## Files to touch

~6-8 files. ~350 lines net delta.

Per-module nuance:
- **embed** — public widget submission endpoint + key issuance/revocation queries. The public `POST /embed/leads` writes a Lead via the leads service — only the embed-keys/config queries move to embed DAL.
- **integrations** — parent OAuth + integration-record queries. Google + Meta sub-folders (`integrations/google/`, `integrations/meta/`) have their own modules; only the parent-level `integrations.service` queries move into `integrations/data_access.py`. Google + Meta sub-modules get their DALs in a future step if they grow them — flagged but not in scope here.
- **invitations** — token lookup, expiry checks, accept/revoke writes. Used by RBAC invite flow.

**Note:** `core/integrations/` does not currently have a `service.py` per the audit (it has `models.py`, `schemas.py`, `router.py`, `module.py`, plus `crypto.py`, `dlq.py`, and `google/` + `meta/` sub-folders). If `service.py` is genuinely absent and the router does its work inline, create `service.py` as part of this step (mechanical — pull the logic out of router) so the layering can land. Document this in the step's stop-report.

## Plan

Same pattern as Step 4.

## DB changes / migrations

None.

## Tests

Run existing pytests.

## Smoke

- **embed:** Settings → Embed → issue a key → use it to submit a public lead → lead appears.
- **integrations:** Settings → Integrations → connect/disconnect a provider → status updates.
- **invitations:** Settings → Users → invite a user → invite email lands → accept invite → user joins org.

## Self-check (10 rules)

Pure relocation (with mechanical service.py extract for integrations if needed). ✓ Stop-and-report. ✓

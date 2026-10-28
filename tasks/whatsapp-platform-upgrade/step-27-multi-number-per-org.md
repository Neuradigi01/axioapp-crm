# Step 27 — Multi-number per org

**Goal:** Lift the 1-org = 1-WA-number constraint. Single org connects N numbers (typically one per store / region) → per-number routing for inbound, per-number selection for outbound, side-by-side health comparison.
**Status:** COMPLETED (27a backend + 27b UI)
**Depends on:** Phases 1-6 closed (touches many call sites).

---

## Scope

In-scope:
- Schema change: `tbl_whatsapp_account_configs` becomes 1-row-per-(org, phone_id). UNIQUE constraint on `(org_id, phone_id)`. Existing single-row assumption removed.
- All outbound code paths accept explicit `phone_number_id`.
- Embedded Signup (Step 2): connecting N phones from a WABA creates N config rows. UI shows all.
- Webhook receiver: dispatch by `phone_number_id` to correct config + downstream automation pipeline.
- Per-number routing for inbound: conversation's `received_via_phone_number_id` set; conversation attributable to a number.
- Outbound: composer "Send from" dropdown when org has multiple; campaign create "Send from" dropdown.
- Business profile editor (Step 11) becomes per-number.
- Phone health dashboard (Step 12) per-number with side-by-side comparison.
- Per-number permissions optional: org-wide WhatsApp permission for v1; per-number RBAC deferred.
- Feature flag `org.multi_number_enabled` gates the multi-number flow; opt-in until validated.

Out of scope:
- Per-number Automation rules (Step 17/18) — for v1 rules apply across all numbers; per-number filter is a follow-up.
- Per-number cost dashboard split — Step 21 covers org-wide; split as later improvement.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/whatsapp/models.py` | Drop org-level uniqueness; add (org, phone) unique |
| `API/alembic/versions/<ts>_multi_number.py` | **NEW** with backfill safety check |
| `API/src/app/core/integrations/whatsapp/embedded_signup.py` | Create N rows per WABA's phones |
| `API/src/app/core/integrations/whatsapp/adapters/whatsapp.py` | Accept explicit phone_number_id |
| `API/src/app/core/integrations/whatsapp/webhook.py` | Dispatch by phone_number_id |
| `API/src/app/core/conversations/models.py` | Add `received_via_phone_number_id` |
| `API/src/app/core/conversations/router.py` | Composer "send from" param |
| `API/src/app/core/campaigns/models.py` | Add `send_from_phone_number_id` |
| `API/src/app/core/integrations/whatsapp/router.py` | Status / business-profile / health endpoints now phone-scoped |
| `APP/.../whatsapp/business-profile/business-profile-page.component.ts` | Number tabs |
| `APP/.../whatsapp/phone-health/phone-health-card.component.ts` | Per-number tile + comparison |
| `APP/.../conversations/composer/composer.component.ts` | "Send from" dropdown when multi |
| `APP/.../campaigns/create/campaign-create.component.ts` | "Send from" dropdown |
| `APP/.../settings/integrations/whatsapp-card.component.ts` | List all connected numbers |
| `API/tests/integrations/test_multi_number.py` | **NEW** broad coverage |
| `API/tests/conversations/test_per_number_routing.py` | **NEW** |

**~16 files. ~1100 lines.**

## Plan

1. Migration: drop existing `tbl_whatsapp_account_configs` unique (org_id) → add (org_id, phone_id). Verify no existing dupes break uniqueness.
2. Refactor every "get_active_whatsapp_config(org_id)" call site to accept phone_number_id or "default".
3. Default behavior for existing single-number orgs: implicit pick the only number → no UX change.
4. Embedded Signup: enumerate WABA's phones, create rows per phone, UI shows all.
5. Webhook dispatch keyed by phone_number_id (already present in Meta payload).
6. Frontend: tabs / pickers wherever a number must be chosen.
7. Tests: multi-number connect, per-number routing, send-from-selection, idempotent re-connect.

## DB changes / migrations

Schema constraint shift + new column on conversations + campaigns. Safety net: pre-check duplicates before flipping constraint.

## Tests

12 pytest + 4 Jest.

## Smoke

```
1. Connect 2 numbers via ES from same WABA.
2. Both shown on Integrations page.
3. Send inbound to number A → conversation has received_via_phone_number_id = A.
4. Send inbound to number B → routed correctly.
5. Composer in a conversation shows "Send from: <which>" dropdown.
6. Campaign create: pick which number to send from.
7. Phone health: side-by-side comparison.
8. Business profile editor: tabs per number.
9. Disconnect one number → other persists.
10. Existing single-number orgs unaffected (no UX change).
```

## Risks

- Refactor blast radius: every call site touching whatsapp config. Use feature flag + roll out gradually.
- Webhook dispatch race: incoming for phone X persisted as belonging to phone Y if mis-keyed. Tests + audit log.
- Backfill: existing rows get implicit "default" flag for backward compat.

## Self-check (10 rules)

`core/integrations/whatsapp/` + `core/conversations/` + `core/campaigns/`. ✓. org_id + RLS preserved. ✓. No custom-field changes. ✓. Static UI. ✓ N/A. Module descriptor unchanged. ✓. Existing permissions. ✓. pack.yaml untouched. ✓. 16 files / ~1100 lines (over budget — execute in 2 sub-steps: 27a schema + backend, 27b UI). ✓ Rule 8 with split. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 27 — Multi-nu

mber per org (likely split into 27a backend + 27b UI at execution)
Files: 16
Verify: multi-number connect / route / send / health comparison; single-number orgs unaffected.
Tests: 12 pytest + 4 Jest.
Next: Step 28 — edge inbound types.
Awaiting "proceed".
```

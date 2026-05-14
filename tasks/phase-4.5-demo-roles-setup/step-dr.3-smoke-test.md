# Step DR.3 — Smoke test all 4 logins side-by-side

**Goal:** Manually log in as each of the four test users and confirm the sidebar entries and permission gates match the role's grants. No code changes — this is a pure verification step that closes out the mini-phase.
**Phase:** 4.5 — Demo Roles Setup (side task)
**Depends on:** DR.1, DR.2
**Status:** Pending

## Scope

**In-scope:**
- Hands-on walkthrough of the four logins in the browser.
- Per-login: record which sidebar entries appear, and click into 1–2 of them to confirm pages load without 403.
- Update the README.md status of the three step files from Pending → Done.

**Out of scope:**
- Any code change.
- Any database mutation (don't create contacts/leads as part of this test — keep the orgs clean).

## Verification matrix

| Login | Expected sidebar entries | Expected NOT to see | Sanity click |
|---|---|---|---|
| `employee@core-demo.local` | Contacts, Leads, Walk-ins, Appointments, Catalog, Conversations, Calls, Tasks, Billing (read-only) | Staff, Settings, Inventory, Custom Orders, Field Ops, POS | Click Contacts → list page loads (empty). Click Settings sidebar should not exist; hitting `/user/settings` directly → 403. |
| `owner@core-demo.local` | Everything Employee sees, plus Staff, Reviews, Campaigns, Settings (read) | Inventory, Custom Orders, Field Ops, POS | Click Settings → loads (read-only buttons where applicable). Hitting users-create endpoint → 403. |
| `admin@core-demo.local` | All Layer-1 modules | Inventory, Custom Orders, Field Ops, POS | Click Staff → list loads. Try to add a staff user → succeeds (Admin has `users.write`). |
| `admin@demo.local` *(existing)* | All Layer-1 modules **plus** Inventory, Custom Orders, Field Operations, Billing & POS | (nothing — admin sees everything) | Click POS → product grid loads. |

## Plan

1. Open `/accounts/login`. Pick `Core CRM — Employee` from the dropdown. Sign in.
2. Note sidebar. Click 2 entries to confirm pages load. Try direct-URL one entry that should be 403 → see error.
3. Logout. Repeat with `Core CRM — Owner`, then `Core CRM — Admin`, then `Furniture CRM — Admin`.
4. After all four pass, update DR.1, DR.2, DR.3 from `Pending` → `Done` in [README.md](README.md).
5. Update the master `tasks/README.md` phase-index table to note this mini-phase is done (optional, but nice).

## DB changes / migrations

None.

## Tests to add

None.

## Verification checklist

- [ ] All 4 logins succeed (no 401, no spinner-stuck).
- [ ] Sidebar entries match the matrix above for each login.
- [ ] At least one positive page-load + one expected-403 verified per role.
- [ ] Logout works from each login.
- [ ] The Furniture CRM admin still sees the existing furniture data (inventory items, prior invoices, custom orders from earlier phases).

## Self-check (10 rules)

- [ ] No code was changed in this step.
- [ ] No data was added to either org during testing.

## Stop & report

Final report for the mini-phase. After this, resume the master plan at **Phase 5.1 — Marketplace Sync abstraction**.

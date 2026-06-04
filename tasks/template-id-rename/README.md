# Rename `pack_id` → `template_id`

A short refactor track to separate two concepts that currently share one column. After this track:

| Identifier | Meaning |
|---|---|
| **`template_id`** (renamed from `pack_id`) | Which vertical CRM the org uses — `furniture`, `base`, `clinic`, `real_estate`, etc. |
| **`pack_id`** | **Freed up.** Reserved for the future subscription-tier work (`basic` / `standard` / `premium`) when that lands. No `pack_id` is read or written by any code after this track. |

Pure rename. No new tables, no new features, no new logic. The same string value (`"furniture"`, `"pending"`, etc.) is stored in a column whose name has changed.

## Why this exists

Manager direction on 2026-06-04: the field that today identifies a tenant's chosen CRM vertical is called `pack_id`, but `pack_id` is wanted later for subscription tiers (basic / standard / premium). Two distinct concepts sharing one column will cause pain when the second one ships. Cheaper to rename **now** (~25 files affected) than after every dashboard, report, billing surface, and admin UI references it (estimated ~80 files in six months).

Done now, the future tier work is purely additive: a new `pack_id` column, a new selector UI, new permission checks — none of which conflict with the vertical identifier.

## What this does NOT do

- Does **not** add a subscription-tier column or any tier-related logic. That's a separate future track.
- Does **not** change the catalog endpoint's URL, behaviour, or set of tiles. Same `/api/v1/packs/catalog` returning the same 10 entries (just with renamed field).
- Does **not** change the onboarding flow logic — same 3-step wizard, same backend writes, same audit events.
- Does **not** change the `packs/` folder name, the `core/packs/` Python module name, or the `pack.yaml` file name. Those refer to the *system* (a package of definitions, like an NPM package) — the rename is only of the *identifier inside* them.
- Does **not** add backward-compatibility aliases. Both halves (backend, frontend) flip at once. There is a brief broken window between Step 1 and Step 2 — see Risks.
- Does **not** rename the legacy `register_with_new_org` path. It still exists, still works with the renamed field (just an internal rename of its variables).
- Does **not** touch any `/admin/...` legacy template UI or `Flutter/`.

## Acceptance criteria

After this track:

1. `organizations.template_id` column exists. `organizations.pack_id` column does **not** exist.
2. `POST /api/v1/auth/onboarding/complete` accepts `{organization_name, template_id, country?, currency?, team_size?}` (note `template_id`, not `pack_id`).
3. `GET /api/v1/packs/catalog` returns tiles with `template_id` key (not `pack_id`).
4. `GET /api/v1/users/me` returns `org.template_id` (not `org.pack_id`).
5. Pack manifests (`pack.yaml`) carry `template_id:` as their top-level identifier field.
6. The string `"pack_id"` does not appear in `api/src/app/core/`, `api/src/app/packs/`, `app/src/app/features/accounts/onboarding/`, or related test files. (Allowed exceptions: comments referencing the historical name, audit log entries from before the rename.)
7. Onboarding flow works end-to-end with the renamed field: register → wizard → org created with `template_id="furniture"` (or whatever was picked).
8. All existing backend pytest suites continue to pass after their references are updated.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Backend rename — DB + Python + pack manifests + tests](step-1-backend-rename.md) | COMPLETED | ~1 day |
| 2 | [Frontend rename — Angular types, services, components](step-2-frontend-rename.md) | Pending | ~½ day |

**Total: ~1½ working days.** Each step independently verifiable; pause and report after each per rule 9. **Step 2 must ship close behind Step 1** — the onboarding flow is broken between them (frontend sends `pack_id`, backend expects `template_id`).

## Dependencies

- Onboarding-setup track — COMPLETED. This rename touches files that track introduced (catalog_config, schemas, auth service, etc.).
- No external deps. No package upgrades. No tooling changes.

## File budget

| Step | Files | Lines | Notes |
|---|---|---|---|
| 1 | ~17–20 | ~250 | **Exceeds rule 8's 10-file ceiling.** Atomic rename across DB column + ORM + Python services + Pydantic schemas + pack manifest schema + YAML files + tests cannot be safely split — every layer references the field name in a way that breaks the others if changed in isolation. Documented and accepted. Same precedent as `onboarding-setup` Step 3 (which went to 11 files for similar reasons). |
| 2 | ~5 | ~80 | Well within budget. Frontend-only. |

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| One canonical name for "which vertical" | `template_id` everywhere — DB, API, manifests, types, identifiers. No aliases. |
| `pack_id` is free | The string `pack_id` (as a column name, field name, or parameter name) does not appear in any post-track code. Reserved for future subscription-tier work. |
| Migration is invertible | Alembic downgrade renames the column back to `pack_id` cleanly. No data loss in either direction. |
| Pack manifest schema bumps no version | `PackManifest.version` field stays at its current value per manifest. The field rename inside the manifest is a schema-level change, not a content-level change. |

## Self-check against the 10 rules

- ✅ Rule 1: `/core` never imports `/packs`. Unchanged — this is a rename, not a structural change.
- ✅ Rule 2: All tenant-scoped tables still have `org_id` + RLS. The renamed column is not `org_id`-related.
- ✅ Rule 3: Custom fields layered model unaffected.
- ✅ Rule 4: No form changes (forms are typed against generated types; types regenerate).
- ✅ Rule 5: Sidebar registry unchanged.
- ✅ Rule 6: Permission registry unchanged.
- ✅ Rule 7: `pack.yaml` source-of-truth role preserved. Only the *name* of one top-level field changes (its semantics, contents, and write path stay identical).
- ⚠️ Rule 8: Step 1 exceeds the 10-file ceiling for the reason documented above. Step 2 is within budget.
- ✅ Rule 9: Stop-and-report after each step.
- ✅ Rule 10: No TODOs. The rename is complete after Step 2 — no half-finished state surviving the track.

## After this track

- `pack_id` is available for whoever ships the subscription-tier work. They add `organizations.pack_id` as a new column (type/length their choice), add a tier-selector UI, add per-tier permission gates, and that all lives in its own track with zero collision risk.
- Any future "what kind of CRM is this org?" code reads `organization.template_id`. Self-documenting.
- The catalog endpoint and onboarding wizard both speak `template_id`. The naming matches what end users and engineers actually mean.

## When to start

Whenever you say go. The whole track is ~1½ days. Step 2 should follow Step 1 within the same session to keep the onboarding flow working.

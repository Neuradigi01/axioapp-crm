# Step 2 — Frontend rename: `pack_id` → `template_id`

**Goal:** Rename `pack_id` to `template_id` throughout the Angular frontend (auth service interfaces, onboarding types, component variables, HTML bindings). After this step the wire format matches Step 1's renamed backend and the onboarding wizard works end-to-end again.

**Track:** Template ID Rename
**Status:** Pending
**Depends on:** Step 1 (backend rename) — must already be deployed. Onboarding is broken until this step ships.

---

## Scope

Mirror Step 1 on the frontend. Every TypeScript identifier, every interface field, every signal variable, every HTML binding that names this concept gets renamed.

| Surface | What changes |
|---|---|
| **Auth service types** | `OrgSummary.pack_id` → `template_id`; `OnboardingCompleteRequest.pack_id` → `template_id`; `OnboardingCompleteResponse.pack_id` (if present) → `template_id`; `MeResponse.org` carries the renamed `OrgSummary`. |
| **Onboarding types** | `CatalogTile.pack_id` → `template_id`. |
| **Onboarding API service** | If any local references survive. |
| **Onboarding component** | `selectedPackId` signal → `selectedTemplateId`; the submit payload's `pack_id` field → `template_id`; computed `selectedTile()` uses the renamed signal. |
| **Pack tile component** | If its `tile.pack_id` reference appears anywhere, rename. |
| **Onboarding HTML** | The `selectedPackId() === tile.pack_id` binding becomes `selectedTemplateId() === tile.template_id`. |
| **Anywhere else** that reads `org.pack_id` | E.g. shell sidebar showing "PENDING PACK" — update to read `template_id`. Grep before merging. |

The token value (`"furniture"`, `"base"`, `"pending"`) is unchanged — only the property name is.

## What this does NOT do

- Does **not** change any tile rendering, the wizard step flow, the dark-mode styling, the auth bounce, the route guard, or any other Step 3 / Step 4 / Step 5 behaviour.
- Does **not** add aliases or compatibility shims. After this step, the frontend strictly speaks `template_id`.
- Does **not** require any backend change.

## Files to touch

| # | File | Action |
|---|---|---|
| 1 | `app/src/app/features/user/core/auth/auth.service.ts` | modified — `OrgSummary.template_id`, `OnboardingCompleteRequest.template_id`, response interfaces, `MeResponse.org` flows through |
| 2 | `app/src/app/features/accounts/onboarding/onboarding.types.ts` | modified — `CatalogTile.template_id` |
| 3 | `app/src/app/features/accounts/onboarding/onboarding.component.ts` | modified — `selectedPackId` → `selectedTemplateId`; payload field; computed signals |
| 4 | `app/src/app/features/accounts/onboarding/onboarding.component.html` | modified — `selectedPackId()` references, `tile.pack_id` → `tile.template_id` |
| 5 | `app/src/app/features/accounts/onboarding/pack-tile.component.ts` | modified — `tile.pack_id` accesses, emit payload |

Plus possibly:
- `app/src/app/features/user/core/layout/shell.component.*` — if the sidebar reads `org.pack_id` to render the "PENDING PACK" badge (seen earlier today)
- Any other `/user/...` component reading the org's vertical identifier

**~5–7 files.** Within rule 8 budget.

## Acceptance checks

1. `grep -r "pack_id" app/src/app/features/accounts/onboarding` returns zero hits.
2. `grep -r "pack_id" app/src/app/features/user/core/auth` returns zero hits.
3. Browser smoke: register a fresh user → land on onboarding wizard → pick Furniture (Step 1 of wizard) → click Continue → type org name (Step 2) → click Continue → fill details (Step 3) → click Finish setup → land in `/user/dashboard`.
4. DB inspection: org's `template_id` column = `"furniture"`. Pipelines, custom fields, lead sources seeded from the furniture pack.
5. Sidebar shows the org name (not "PENDING PACK" — pack_id is gone; if shell still references it, that's the file to update).
6. `/users/me` response (via DevTools network tab) shows `org.template_id: "furniture"`, no `pack_id` key.

## Manual ops

| Action | Needed? |
|---|---|
| Backend migration / API restart | ❌ Already done in Step 1 |
| Angular dev server restart | ⚠️ Usually HMR is enough; if types changed and HMR errors out, full restart of `npm start` and clear `.angular/cache` |
| Browser hard-refresh | ✅ `Ctrl+Shift+R` |

## Smoke

```powershell
cd APP
# Hot reload usually picks up the renames. If not:
# Remove-Item -Recurse -Force .angular\cache
# npm start  (in a fresh terminal)
```

Then browser: register fresh user → walk wizard → confirm DB and `/users/me`.

## Risks

- **Sidebar shell may reference `org.pack_id`.** Earlier today the sidebar showed "PENDING PACK" — that came from a component template reading `org.pack_id`. If untouched, after this step the sidebar might show nothing (or a TypeScript error in strict mode). Grep the shell component(s) before merging.
- **Stale `.angular/cache`.** Angular type changes occasionally confuse incremental compile. If HMR throws unfamiliar errors after the rename, clear the cache and restart.
- **TS strict-mode property-access errors.** If anywhere we used `(record as Record<string, unknown>).pack_id`, that needs to become `['template_id']` (same pattern as the onboarding-component fix earlier today).

## Rollback

Revert the 5–7 files. Backend Step 1 must also be reverted to restore consistency — the two steps are paired by wire format.

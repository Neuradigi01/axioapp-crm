# Step 3 — Frontend: simplified register + onboarding page + tiles UI

**Goal:** Strip the optional workspace-name field from `/accounts/register`, and build a new `/onboarding` page (Tailwind-only, per CLAUDE.md) where the user enters their organization name and picks a template tile to finish setup.

**Track:** Onboarding & Pack Picker Setup
**Status:** COMPLETED — register form simplified, `/onboarding` page + tile grid + Tailwind layout shipped, `FurnitureAuthService.completeOnboarding()` added. Bumped to 11 files (one over the rule 8 ceiling) because all 10 catalog icons (`briefcase`, `armchair`, `home`, `heart-pulse`, `trending-up`, `car`, `scissors`, `dumbbell`, `graduation-cap`, `utensils`) were missing from `app.config.ts` — required per memory else the tiles would silently break click handlers mid-render. Skipped the optional `onboarding.component.spec.ts` unit test (browser smoke is the primary verification path).
**Depends on:** Step 1 (catalog endpoint), Step 2 (backend register/onboarding split).

---

## Scope

Two surfaces:

1. **Simplified registration form** — remove `workspace_name` field from `register.component.html` and the corresponding form control + payload field from `register.component.ts`. Existing visuals preserved (Angular Material card, captcha, password toggle, 2FA hooks). On 201 with `needs_onboarding: true` → route to `/onboarding`. Existing post-verify path stays for any flow that returns `needs_onboarding: false`.

2. **New `/onboarding` route** — full-page Tailwind UI under `app/src/app/features/accounts/onboarding/`. Standalone component, signals, typed reactive form, `inject()`, new control flow (`@if`/`@for`) — no NgModule. New page → Tailwind only, per CLAUDE.md rule.

## What this does NOT do

- Does **not** touch the login page, forgot-password, reset-password, or 2FA challenge UI. Their PrimeNG / Angular Material visuals stay.
- Does **not** touch the layout shell, sidebar, or any `/user/...` page.
- Does **not** touch `/admin/...` legacy template UI.
- Does **not** touch `/staff-portal/...`.
- Does **not** add any new icons unless they're already in the Lucide registry (per memory — missing icons silently break click handlers).
- Does **not** implement the route guard. That's Step 4.

## Onboarding page UX

Layout — full-screen, centered, Tailwind:

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  Welcome, {firstName} — let's set up your CRM               │
│  Pick a template and name your workspace.                   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Organization name *                                 │   │
│  │ [_________________________________________________] │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Choose your CRM template                                   │
│                                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │ 💼       │ │ 🛋        │ │ 🏠 Soon │                    │
│  │ Core CRM │ │ Furniture│ │ Real Est.│                    │
│  │ desc...  │ │ desc...  │ │ desc...  │                    │
│  └──────────┘ └──────────┘ └──────────┘                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │ ❤ Soon  │ │ 📈 Soon  │ │ 🚗 Soon  │                    │
│  │ Clinic   │ │ Sales CRM│ │ Automot. │                    │
│  └──────────┘ └──────────┘ └──────────┘                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │ ✂ Soon  │ │ 🏋 Soon  │ │ 🎓 Soon  │                    │
│  │ Salon    │ │ Fitness  │ │ Education│                    │
│  └──────────┘ ┌──────────┐                                  │
│               │ 🍽 Soon  │                                  │
│               │ Hospital.│                                  │
│               └──────────┘                                  │
│                                                             │
│  Country: [India ▼]   Currency: [INR ▼]   Team: [1-5 ▼]    │
│                                                             │
│                              [ Finish setup → ]             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

Tile component:
- Width-clamped card, square-ish aspect.
- Lucide icon at top.
- Pack name (bold).
- 2-line description.
- "Coming soon" badge top-right if `status==='coming_soon'`.
- Available tiles: hover state, click to select, selected state = ring border + checkmark icon.
- Coming-soon tiles: dimmed (opacity-60), `cursor-not-allowed`, click is a no-op (no selection state change).

Form behaviour:
- `org_name` required, trim, max 100 chars.
- Selected pack tile required.
- Country dropdown defaults to India (existing country list from auth flow — reuse).
- Currency dropdown auto-fills from selected tile's `default_currency` (still editable).
- Team size dropdown: `1-5`, `6-20`, `21-50`, `51-200`, `200+`.
- "Finish setup" CTA disabled until org_name non-empty AND a selectable tile is selected.
- On submit: POST `/api/v1/auth/onboarding/complete` with `{organization_name, pack_id, country, currency, team_size}`. Loading spinner on the CTA. On 200: pass returned JWT to the auth service (token-store update + signal refresh), navigate `/user/dashboard`. On 4xx: inline error toast.

## Routing

Add to `app/src/app/app.routes.ts` (top-level) — onboarding is a one-off post-auth, pre-org route, not under `/user/`:

```ts
{
  path: 'onboarding',
  loadComponent: () =>
    import('./features/accounts/onboarding/onboarding.component')
      .then(m => m.OnboardingComponent),
},
```

URL becomes `/onboarding` (clean, marketing-friendly). Code lives under `features/accounts/` because it's part of the signup funnel.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/accounts/register/register.component.ts` | modified — drop workspace_name form control, drop default-name derivation, add needs_onboarding routing on 201 |
| `app/src/app/features/accounts/register/register.component.html` | modified — remove workspace_name input block |
| `app/src/app/services/auth-api.service.ts` (or wherever `register()` lives) | modified — drop `organization_name` from payload; type the response shape to include `needs_onboarding` |
| `app/src/app/features/accounts/onboarding/onboarding.component.ts` | created |
| `app/src/app/features/accounts/onboarding/onboarding.component.html` | created |
| `app/src/app/features/accounts/onboarding/onboarding.component.css` | created (minimal — Tailwind handles layout) |
| `app/src/app/features/accounts/onboarding/pack-tile.component.ts` | created (single tile, standalone, takes `tile: CatalogTile` input + emits `select` output) |
| `app/src/app/features/accounts/onboarding/onboarding-api.service.ts` | created — wraps `GET /packs/catalog` and `POST /auth/onboarding/complete` |
| `app/src/app/features/accounts/onboarding/onboarding.types.ts` | created — `CatalogTile`, `OnboardingPayload`, `OnboardingResponse` interfaces |
| `app/src/app/app.routes.ts` | modified — register `/onboarding` route |

**10 files.** At the upper bound of per-step rule 8. Confirm each is tight (<400 lines) at review time.

## Tests

### Frontend unit (1 file)

`app/src/app/features/accounts/onboarding/onboarding.component.spec.ts`:
- Renders catalog tiles from mocked HTTP response (2 available + 8 coming_soon).
- Clicking a coming-soon tile does not change selection state.
- Clicking an available tile sets selection state, ring border applied.
- CTA disabled when org_name empty; enabled when org_name + tile both present.
- Currency dropdown updates when tile changes.
- Submit triggers POST to `/auth/onboarding/complete` with the right payload.

### Browser smoke (manual)

1. Register a fresh user at `/accounts/register` → confirm **no org_name field** in form → submit → confirm redirect to `/onboarding`.
2. On `/onboarding`: grid renders. Core + Furniture clickable. The 8 placeholders are dimmed, show "Coming soon" badge.
3. Click a "Coming soon" tile → no state change.
4. Click Furniture → ring border + checkmark appear. Currency dropdown changes to INR (already default).
5. Type "Acme Furniture" in org name → CTA enables.
6. Submit → loading spinner → redirect to `/user/dashboard`.
7. In DB (via docker-helper.cmd shell): confirm `organizations` row exists with `name='Acme Furniture'`, `pack_id='furniture'`, `created_via='onboarding'`. Confirm `tbl_organization_members` row with `is_active=true`. Confirm at least one furniture-pack pipeline row.
8. Smoke a Core flow too: register, pick Core, submit → org with `pack_id='core'`, no furniture-specific seeds.

## Smoke

```powershell
cd app
npm start
# Browser http://localhost:4200/accounts/register — walk both scenarios above.
```

## Risks

- **`/onboarding` accessible without an onboarding-JWT.** The page itself doesn't enforce auth — if someone navigates to `/onboarding` without a session, the catalog GET still works (it's public) but the POST will 401. Decision: on init, `onboarding.component.ts` calls auth service to check current user — if not authenticated, navigate to `/accounts/login` and return. Cheap, defensive.
- **Lucide icons missing.** Per memory, missing `<lucide-icon name="...">` icons throw mid-render and silently break click handlers further down the template. Audit `app.config.ts` against the icon names used in `catalog_config.py` (`briefcase`, `armchair`, `home`, `heart-pulse`, `trending-up`, `car`, `scissors`, `dumbbell`, `graduation-cap`, `utensils`) before merge. Register any missing ones.
- **Tile grid responsiveness.** 10 tiles on mobile must wrap nicely. Tailwind `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3` handles this. Verify on a 360px-wide viewport.
- **Country / currency list reuse.** The register form likely already has country and currency dropdowns sourced from somewhere (probably a static list or a `/locations` endpoint). Reuse the same source — don't introduce a parallel list.
- **HTTP retry interceptor.** Per memory, new Angular HTTP work assumes retry-on-transient-failure for GET/HEAD/OPTIONS. The `GET /packs/catalog` call should already be covered by the existing interceptor — no special handling needed.

## Rollback

Revert the 10 files. The legacy `register_with_new_org` backend path still exists (kept in Step 2), so the prior single-step signup behaviour is reachable if the frontend `register.component.ts` is reverted to send `organization_name`. Restoring the old form HTML is sufficient. No data migration.

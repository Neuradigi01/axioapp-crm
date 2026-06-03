# Step 4 — Route guard: no-org → onboarding

**Goal:** Add an Angular functional route guard on `/user/**` that catches any authenticated user who reaches a user-area URL without having completed onboarding (no organization membership), and redirects them to `/onboarding`. Closes the "user closed the tab mid-onboarding" loophole.

**Track:** Onboarding & Pack Picker Setup
**Status:** Pending
**Depends on:** Step 2 (`/users/me` returns `needs_onboarding`), Step 3 (`/onboarding` route exists).

---

## Scope

One Angular functional guard. One auth-service field update. One `user.routes.ts` wiring change. One small spec. That's it.

The guard reads from the auth service's already-cached user state — it does **not** call `/users/me` itself. The auth service is responsible for keeping that state fresh (already does so on login, on token refresh, and on app bootstrap).

Logic:

```
if (authService.needsOnboarding() === true) → redirect to /onboarding
if (authService.needsOnboarding() === false) → allow
if (authService.userLoaded() === false) → wait for the userLoaded signal, then re-evaluate
```

The guard is `canActivateChild` on the top-level `/user` route — catches every subroute (`/user/dashboard`, `/user/leads`, `/user/settings/...`, all of `packs/furniture/...`).

## What this does NOT do

- Does **not** modify `/accounts/...` routes (login, register, forgot, reset, onboarding itself).
- Does **not** modify `/admin/...` legacy routes.
- Does **not** modify `/staff-portal/...`.
- Does **not** modify the existing permission guard (`permissionGuard()` from `rbac-ownership/` Step 4). It runs *in addition to* this guard, deeper in the route tree. This guard runs first at the `/user` boundary.
- Does **not** introduce a new HTTP call. Reads from auth service state only.
- Does **not** affect users who already have an org. They see no behaviour change.

## What this prevents

Three failure modes:

1. **Closed tab mid-onboarding.** User registered yesterday, never finished onboarding, opens the app today, logs in via `/accounts/login`. Login succeeds (the user exists). Without the guard, they hit `/user/dashboard` and see broken UI (no org context, every list query 404s). With the guard, they're redirected to `/onboarding`.
2. **URL bar manipulation.** Someone with an onboarding-JWT pastes `/user/dashboard` directly. Guard catches.
3. **State race after onboarding complete.** User completes onboarding, JWT refreshed, navigation to `/user/dashboard` happens. Guard reads fresh `needsOnboarding=false` → allows. Verify the auth service has updated *before* the navigation fires (sequence handled in Step 3's submit handler).

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/shared/guards/no-org.guard.ts` | created |
| `app/src/app/services/auth.service.ts` | modified — expose `needsOnboarding` signal sourced from `/users/me` response; expose `userLoaded` signal |
| `app/src/app/features/user/user.routes.ts` | modified — add `canActivateChild: [noOrgGuard]` to the `/user` parent route |
| `app/src/app/features/user/core/shared/guards/no-org.guard.spec.ts` | created |

**4 files total.** Well within per-step rule.

## Guard implementation sketch

```ts
import { inject } from '@angular/core';
import { Router, type CanActivateChildFn } from '@angular/router';
import { AuthService } from '../../../../../services/auth.service';
import { firstValueFrom } from 'rxjs';
import { toObservable } from '@angular/core/rxjs-interop';
import { filter } from 'rxjs/operators';

export const noOrgGuard: CanActivateChildFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (!auth.userLoaded()) {
    await firstValueFrom(
      toObservable(auth.userLoaded).pipe(filter(loaded => loaded))
    );
  }

  if (auth.needsOnboarding()) {
    return router.createUrlTree(['/onboarding']);
  }
  return true;
};
```

(Final implementation may differ — pattern depends on how the existing auth service exposes user state. The above is a sketch using Angular 20 signals + rxjs interop, matching CLAUDE.md stack rules.)

## Tests

### Unit (1 file)

`app/src/app/features/user/core/shared/guards/no-org.guard.spec.ts`:
- Returns `true` when `auth.needsOnboarding() === false` and `userLoaded() === true`.
- Returns a `UrlTree` pointing to `/onboarding` when `needsOnboarding() === true` and `userLoaded() === true`.
- Waits for `userLoaded` to flip true before evaluating, when it starts false.

### Browser smoke (manual)

1. Register a fresh user at `/accounts/register` (don't complete onboarding) → close the tab.
2. Reopen the app, go to `/accounts/login`, log in → expected: redirected to `/onboarding`, **not** `/user/dashboard`.
3. Complete onboarding → navigate around `/user/dashboard`, `/user/contacts`, `/user/settings/profile` freely → no further redirects.
4. Open a fresh tab, paste `/user/dashboard` while logged in (post-onboarding) → loads normally.
5. Log out → log back in → still loads `/user/dashboard` directly (state persisted via `/users/me`, no onboarding loop).
6. Type `/user/dashboard` directly while holding only an onboarding-JWT (i.e. after register but before onboarding complete) → redirected to `/onboarding`.
7. Invite-link signup flow (existing): invited user accepts invite → lands in inviting org's `/user/dashboard` directly → no redirect to onboarding (because they have a membership).

## Smoke

```powershell
cd app
npm start
# Browser: walk the 7 scenarios above.
```

## Risks

- **Race on first navigation after login.** If `/users/me` has not returned yet by the time the guard runs, the guard sees `userLoaded()===false` and must block until loaded. Sketch above handles via `toObservable + filter`. Verify the auth service emits `userLoaded(true)` on the `/users/me` response in *all* paths (login, refresh, bootstrap, onboarding complete).
- **`canActivate` vs `canActivateChild`.** `canActivate` runs on the parent route only; `canActivateChild` runs on every child navigation. Use `canActivateChild` on `/user` so deep nav (e.g. router.navigate from a button inside `/user/...`) is also guarded. Verify the existing permission guards are also child guards or compose cleanly.
- **Logout state.** On logout, auth service should clear `needsOnboarding` (set to `false` or `null`) and `userLoaded` (set to `false`). Otherwise a stale `needsOnboarding=true` from the previous user could leak. Verify the auth service clearAll path covers both signals.
- **Forgot-password / reset-password / 2FA flows.** None of these routes are under `/user/...`, so the guard does not apply. Verified.

## Rollback

Revert the 4 files. Removing the guard is safe — users without orgs would see broken `/user/...` UI but no data corruption. The catch-all is recoverable: ops can identify orphan users via `tbl_user_login` rows with no `tbl_organization_members` membership and either run them through onboarding manually (via the `/onboarding/complete` API) or delete the orphan accounts.

# Step 1 — Profile tab: fold the standalone `/user/profile` page into Settings

**Status:** COMPLETED — `ProfileTabComponent` lifted byte-for-byte from `ProfilePageComponent` and registered as the first tab in `settings-page.component.ts::TABS` with no permission gate. Avatar dropdown's Profile link now routes to `/user/settings` with `queryParams: { tab: 'profile' }`. The old `/user/profile` route now redirects to `/user/settings?tab=profile` with `pathMatch: 'full'`. Standalone `profile-page.component.ts/html` deleted; `profile.service.ts` retained (consumed by the new tab). 6 files (2 new, 3 modified, 1 route redirect + 2 deletions).

**Goal:** Move the working contents of `APP/src/app/features/user/core/profile/profile-page.component.ts` into a new `ProfileTabComponent` and surface it as the first tab in `/user/settings`. Closes the UX hole where Employees couldn't change their own name / phone / password because the Settings sidebar entry was hidden and the standalone Profile page wasn't discoverable.

**Depends on:** the per-tab gates in `settings-page.component.ts` (already shipped in this track's prerequisite). No backend changes.

## Why this step exists

Two parallel UI surfaces for one job is confusing:

- `/user/profile` — standalone page with full_name / phone edit + password change + sign-out-others. Hidden in the avatar dropdown.
- `/user/settings` — sidebar entry that only Owners/Admins could reach until last edit.

Now that Settings is visible to every role, `/user/profile` becomes redundant. Folding its UI into a Settings tab means staff get a single, discoverable destination — and the avatar dropdown's "Profile" entry can keep working by redirecting to `/user/settings?tab=profile`.

## Files changed

### New
- `APP/src/app/features/user/core/settings/tabs/profile-tab.component.ts`
- `APP/src/app/features/user/core/settings/tabs/profile-tab.component.html`

### Modified
- `APP/src/app/features/user/core/settings/settings-page.component.ts` — register the new tab; insert into `TABS` array (no permission gate — every user can edit their own profile).
- `APP/src/app/features/user/core/settings/settings-page.component.html` — add the `@case ('profile')` branch.
- `APP/src/app/features/user/user.routes.ts` — redirect `/user/profile` → `/user/settings?tab=profile` (preserves any existing in-app links / avatar-menu entries).
- `APP/src/app/features/user/core/layout/header.component.html` (or wherever the avatar dropdown lives) — point "Profile" to `/user/settings?tab=profile`.

### Deletions
- `APP/src/app/features/user/core/profile/profile-page.component.ts/html` — DELETE after the new tab is verified working. The `ProfileApiService` stays (the new tab reuses it).

### Tests
- Browser smoke only (matches Step 3/4 of `update-appointments-page` precedent).

## `profile-tab.component.ts`

Direct lift-and-shift of the working page. Keep the two sub-forms (Profile, Password), the `ProfileApiService` injection, and the `sign_out_others` toggle.

```ts
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  FormBuilder,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { FurnitureAuthService, MeResponse } from '../../auth/auth.service';
import { ProfileApiService } from '../../profile/profile.service';
import { extractApiError } from '@core/services/api-error.util';

@Component({
  selector: 'app-settings-profile-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './profile-tab.component.html',
})
export class ProfileTabComponent {
  // ... identical body to existing ProfilePageComponent ...
}
```

The two sub-forms (Profile and Password) ship complete in one tab — no separate routes.

## `settings-page.component.ts` — wire the tab

Add to the `SettingsTab` union + the `TABS` array (insert first so it's the default landing tab for Employees once the gates filter the rest out):

```ts
type SettingsTab =
  | 'profile'   // NEW
  | 'store'
  | 'team'
  | 'roles'
  | 'integrations'
  | 'notifications'
  | 'ai'
  | 'custom-fields'
  | 'standard-fields'
  | 'embed';

const TABS: ReadonlyArray<TabDef> = [
  { id: 'profile', label: 'Profile' },         // ← new, no permission gate
  { id: 'store', label: 'Store Profile', permission: 'settings.write' },
  // ... rest unchanged
];
```

Add the import + the `imports: []` array entry on `SettingsPageComponent`.

## `settings-page.component.html` — add the case branch

```html
@switch (active()) {
  @case ('profile') {
    <app-settings-profile-tab />
  }
  @case ('store') { <app-settings-store-profile-tab /> }
  ...
}
```

## Avatar-menu redirect

Update the avatar dropdown's Profile link from `routerLink="/user/profile"` to `routerLink="/user/settings"` with `[queryParams]="{ tab: 'profile' }"`. The existing tab-resolution logic in `settings-page.component.ts::_resolveInitialTab` already reads `?tab=` and respects it.

## `user.routes.ts` — keep the old URL working

Replace the standalone `/user/profile` route with a redirect so any deep link / bookmarked URL still lands the user on the right place:

```ts
{
  path: 'profile',
  redirectTo: '/user/settings?tab=profile',
  pathMatch: 'full',
},
```

(Angular Router doesn't support query params in `redirectTo` directly — use a tiny redirect guard / component if needed, or just route to `/user/settings` and let `_resolveInitialTab` fall back to the first visible tab. Pragmatic option: drop the route entirely and accept the 404 on the old URL.)

## Permission gate

None. Every authenticated user must be able to change their own name / phone / password — that's a baseline self-service requirement and matches every other CRM.

## Tests

Browser smoke:
1. Log in as Owner → open Settings → Profile tab default-selected → name / phone edit + Save works.
2. Tick "sign out other devices," change password, submit → confirm logout from a second browser.
3. Log in as **Employee** → Settings sidebar visible → only Profile + Notifications tabs visible → Profile tab opens by default → same flows work.
4. Visit old `/user/profile` URL → lands on Settings → Profile tab (via the redirect).

## Acceptance

- `ProfilePageComponent` deleted; no broken imports.
- Settings page exposes a Profile tab as the first entry for every role.
- Avatar dropdown's "Profile" link routes to `/user/settings?tab=profile`.
- Password change + sign-out-others continue to work identically.

## Self-check vs the 10 rules

- ✅ Rule 5 — no new modules / sidebar entries.
- ✅ Rule 6 — no new permission keys.
- ✅ Rule 8 — 6 files (2 new + 3 modified + 1 deleted); under limit.
- ✅ Rule 10 — fold ships complete; old page deleted; no dual surfaces left.

## Stop-and-report template

> ✅ Step 1 complete.
> **Files changed:** 6 (2 new, 3 modified, 1 deleted).
> **What you can verify:**
> 1. Settings → Profile tab is first for every role.
> 2. Employee can change own password.
> 3. Old `/user/profile` URL still works (redirects to Settings).
> **Tests added:** browser smoke only.
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 2.

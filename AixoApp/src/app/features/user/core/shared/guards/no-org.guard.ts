import { inject } from '@angular/core';
import { CanActivateChildFn, Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { FurnitureAuthService } from '../../auth/auth.service';

/**
 * Route guard for `/user/**`.
 *
 * Bounces self-signup users whose onboarding is still pending back to
 * `/onboarding`. Catches three cases:
 *
 *   1. Closed tab mid-onboarding, then logs back in — guard sees the
 *      pending state from `/users/me` and redirects.
 *   2. Direct URL navigation to `/user/dashboard` with an
 *      onboarding-state JWT — same redirect.
 *   3. Post-onboarding completion — guard reads fresh
 *      `needsOnboarding=false` and allows.
 *
 * Lazy-loads `/users/me` on the first `/user/**` navigation. The
 * shell's header component also calls `me()` in `ngOnInit`; we accept
 * one extra round-trip on the very first page load so the guard has
 * authoritative state without depending on the shell mounting first
 * (chicken-and-egg with `canActivateChild` blocking shell mount).
 *
 * `furnitureAuthGuard` already runs on the `/user` parent route to
 * verify a token exists, so this guard can assume `isAuthenticated()`
 * is true when it runs.
 */
export const noOrgGuard: CanActivateChildFn = async () => {
  const auth = inject(FurnitureAuthService);
  const router = inject(Router);

  if (!auth.userLoaded()) {
    try {
      await firstValueFrom(auth.me());
    } catch {
      // `/users/me` failed — typically a server-revoked session
      // (401) or transient network error. `furnitureAuthGuard` only
      // checks for token presence; this is the right place to catch
      // a token that's no longer valid server-side. Clear local
      // state and bounce to login so the user re-authenticates
      // cleanly rather than seeing a broken shell.
      auth.clearSession();
      return router.createUrlTree(['/accounts/login']);
    }
  }

  if (auth.needsOnboarding()) {
    return router.createUrlTree(['/onboarding']);
  }

  return true;
};

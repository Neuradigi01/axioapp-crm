import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { StaffSessionService } from './staff-session.service';

/**
 * Route guard for the staff-portal authenticated sub-tree. Re-checks
 * the local token's expiry on every navigation. Expired/missing → redirect
 * back to `/staff-portal/login`, dropping any stale token along the way.
 */
export const staffGuard: CanActivateFn = () => {
  const session = inject(StaffSessionService);
  const router = inject(Router);

  if (session.isAuthenticated()) {
    return true;
  }
  session.clear();
  return router.parseUrl('/staff-portal/login');
};

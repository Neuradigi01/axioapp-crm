import { CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';

import { TokenStorageService } from './token-storage.service';

/** Logged-in gate for `/user/...`. Unauthenticated visitors land on the
 *  login page with their intended URL preserved as `?return_url=`. */
export const furnitureAuthGuard: CanActivateFn = (_route, state) => {
  const storage = inject(TokenStorageService);
  const router = inject(Router);

  if (storage.getAccess()) {
    return true;
  }

  return router.createUrlTree(['/accounts/login'], {
    queryParams: { return_url: state.url },
  });
};

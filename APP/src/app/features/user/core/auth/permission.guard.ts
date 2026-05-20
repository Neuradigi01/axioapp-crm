import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';

import { FurnitureAuthService } from './auth.service';
import { TokenStorageService } from './token-storage.service';

/**
 * Permission-key route guard. Use with `canActivate`:
 *
 *   { path: 'billing', canActivate: [permissionGuard('billing.read')], … }
 *
 * If the user isn't authenticated, bounce to `/accounts/login` with
 * `?return_url=<original>`. If they're authed but the cached
 * `currentPermissions` signal hasn't loaded yet, fetch `/users/me`
 * synchronously and re-check. If perms are missing, redirect to
 * `/user/access-denied` carrying `required` + `return_url`.
 *
 * The guard never special-cases roles — Owner / Admin pass the check
 * by virtue of holding the required keys in their grant set. Owner-only
 * affordances must use a dedicated check (see ownership-transfer).
 */
export const permissionGuard = (...required: string[]): CanActivateFn => {
  return (_route, state) => {
    const auth = inject(FurnitureAuthService);
    const storage = inject(TokenStorageService);
    const router = inject(Router);

    if (!storage.getAccess()) {
      return router.createUrlTree(['/accounts/login'], {
        queryParams: { return_url: state.url },
      });
    }

    const denied = (missing: string[]) =>
      router.createUrlTree(['/user/access-denied'], {
        queryParams: { required: missing.join(','), return_url: state.url },
      });

    const cached = auth.currentPermissions();
    if (cached.length > 0) {
      const missing = required.filter((k) => !cached.includes(k));
      return missing.length === 0 ? true : denied(missing);
    }

    return auth.me().pipe(
      map((me) => {
        const missing = required.filter(
          (k) => !me.permission_keys.includes(k),
        );
        return missing.length === 0 ? true : denied(missing);
      }),
      catchError(() =>
        of(
          router.createUrlTree(['/accounts/login'], {
            queryParams: { return_url: state.url },
          }),
        ),
      ),
    );
  };
};

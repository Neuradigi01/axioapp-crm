import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';

import { FurnitureAuthService } from './auth.service';

/**
 * Vertical-pack route guard. Use with `canActivate`:
 *
 *   { path: 'field-ops', canActivate: [packGuard('furniture'), …], … }
 *
 * Pack pages only exist for orgs on that pack — permission keys alone
 * are not enough, a stray grant must not surface furniture pages on a
 * real-estate org. Orgs on another pack are sent back to `/user`. The
 * backend mirrors this with `require_pack` on every pack router.
 */
export const packGuard = (packId: string): CanActivateFn => {
  return () => {
    const auth = inject(FurnitureAuthService);
    const router = inject(Router);

    const decide = (templateId: string | undefined) =>
      templateId === packId ? true : router.createUrlTree(['/user']);

    const org = auth.currentOrg();
    if (org) return decide(org.template_id);

    return auth.me().pipe(
      map((me) => decide(me.org.template_id)),
      catchError(() => of(router.createUrlTree(['/user']))),
    );
  };
};

import { Routes } from '@angular/router';

import { PublicShellComponent } from './shared/public-shell.component';

/**
 * Public property routes. Both hang off `''` under the shared
 * `PublicShellComponent`. Mounted at the app-routes root as a peer
 * of `/user` and `/accounts` — order matters: keep this above the
 * catch-all so `/properties` and `/property/{token}` resolve here
 * instead of falling through to `/accounts` redirects.
 *
 * The routes intentionally require no auth guard. The backend
 * `/api/public/*` endpoints authenticate the token itself.
 */
export const PUBLIC_ROUTES: Routes = [
  {
    path: '',
    component: PublicShellComponent,
    children: [
      {
        path: 'properties',
        loadComponent: () =>
          import('./property-listing/property-listing.component').then(
            (m) => m.PublicPropertyListingComponent,
          ),
      },
      {
        path: 'property/:token',
        loadComponent: () =>
          import('./property-detail/property-detail.component').then(
            (m) => m.PublicPropertyDetailComponent,
          ),
      },
    ],
  },
];

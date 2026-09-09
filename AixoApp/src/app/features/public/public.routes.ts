import { Routes } from '@angular/router';

import { PublicShellComponent } from './shared/public-shell.component';

/**
 * Public routes. Both entity families (real-estate properties and
 * core catalog products) hang off ``''`` under the shared
 * ``PublicShellComponent``. Mounted at the app-routes root as a peer
 * of ``/user`` and ``/accounts`` — order matters: keep this above the
 * catch-all so ``/properties``, ``/property/{token}``, ``/catalog``,
 * and ``/product/{token}`` resolve here instead of falling through
 * to ``/accounts`` redirects.
 *
 * These routes intentionally require no auth guard. The backend
 * ``/api/public/*`` endpoints authenticate the token itself.
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
      {
        path: 'catalog',
        loadComponent: () =>
          import('./product-listing/product-listing.component').then(
            (m) => m.PublicProductListingComponent,
          ),
      },
      {
        path: 'product/:token',
        loadComponent: () =>
          import('./product-detail/product-detail.component').then(
            (m) => m.PublicProductDetailComponent,
          ),
      },
    ],
  },
];

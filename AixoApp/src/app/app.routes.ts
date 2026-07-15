import { Routes } from '@angular/router';
import { authGuard } from '@core/guards/auth.guard';
import { getRoute } from '@core/services/routes-helper.service';
import { furnitureAuthGuard } from './features/user/core/auth/auth.guard';

export const appRoutes: Routes = [
  {
    path: '',
    redirectTo: getRoute('accounts').path,
    pathMatch: 'full',
  },
  {
    path: getRoute('accounts').path,
    loadChildren: () => import('./features/accounts/accounts.routes').then((m) => m.accountsRoutes),
  },
  {
    // Public marketing pricing page. Reachable without auth (peer of
    // `/accounts/...` and `/user/...`, not nested in either). Step 14
    // of the pricing-and-billing track ships the page itself; the
    // "Start free trial" CTA forwards `plan` + `cycle` query params
    // into the signup flow.
    path: 'pricing',
    loadComponent: () => import('./features/pricing/pricing.page').then((m) => m.PricingPage),
  },
  {
    // Meta-mandated public status page for Data Deletion Callback
    // requests (whatsapp-platform-upgrade Step 4). Reachable without
    // auth — the deleted Meta user has no Core CRM account by
    // definition. The route stays valid forever because Meta itself
    // periodically re-fetches it months after the original deletion.
    path: 'data-deletion-status',
    loadComponent: () =>
      import('./features/accounts/data-deletion-status.component').then(
        (m) => m.DataDeletionStatusComponent,
      ),
  },
  {
    // Onboarding picker — landed on after self-signup, while the
    // user's org is still in `template_id="pending"`. Top-level (not under
    // `/user`) because the user has no fully-set-up org yet, so any
    // `/user/...` query would 404 or render a broken shell. The
    // component bounces unauthenticated visitors to `/accounts/login`.
    path: 'onboarding',
    loadComponent: () =>
      import('./features/accounts/onboarding/onboarding.component').then(
        (m) => m.OnboardingComponent,
      ),
  },
  {
    // Public Real Estate pack surfaces — `/properties?org=<slug>` grid
    // and `/property/{token}` detail. No auth guard: the backend's
    // Fernet-token check is the only gate. Placed above `/user/*` and
    // the `**` catchall so route ordering picks these up first.
    path: '',
    loadChildren: () => import('./features/public/public.routes').then((m) => m.PUBLIC_ROUTES),
  },
  {
    path: getRoute('user').path,
    loadChildren: () => import('./features/user/user.routes').then((m) => m.userRoutes),
    canActivate: [furnitureAuthGuard],
  },
  {
    path: getRoute('admin').path,
    loadChildren: () => import('./features/admin/admin.routes').then((m) => m.adminRoutes),
    canActivate: [authGuard],
    data: { role: 'Admin' },
  },
  {
    path: 'staff-portal',
    loadChildren: () =>
      import('./staff-portal/staff-portal.routes').then((m) => m.staffPortalRoutes),
  },
  {
    path: '**',
    redirectTo: getRoute('accounts').path,
  },
];

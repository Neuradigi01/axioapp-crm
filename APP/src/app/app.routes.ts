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
    loadChildren: () =>
      import('./features/accounts/accounts.routes').then(
        (m) => m.accountsRoutes
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
    path: getRoute('user').path,
    loadChildren: () =>
      import('./features/user/user.routes').then((m) => m.userRoutes),
    canActivate: [furnitureAuthGuard],
  },
  {
    path: getRoute('admin').path,
    loadChildren: () =>
      import('./features/admin/admin.routes').then((m) => m.adminRoutes),
    canActivate: [authGuard],
    data: { role: 'Admin' },
  },
  {
    path: 'staff-portal',
    loadChildren: () =>
      import('./staff-portal/staff-portal.routes').then(
        (m) => m.staffPortalRoutes,
      ),
  },
  {
    path: '**',
    redirectTo: getRoute('accounts').path,
  },
];

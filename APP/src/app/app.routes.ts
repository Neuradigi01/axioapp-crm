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
    path: '**',
    redirectTo: getRoute('accounts').path,
  },
];

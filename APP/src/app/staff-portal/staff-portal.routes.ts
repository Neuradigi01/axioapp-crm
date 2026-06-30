import { Routes } from '@angular/router';

import { staffGuard } from './staff.guard';

/**
 * Tablet-only route tree mounted at `/staff-portal`. The login page
 * is unguarded; everything under the shell goes through `staffGuard`
 * which checks the locally-stored staff token's expiry.
 */
export const staffPortalRoutes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./login/login.page').then((m) => m.StaffPortalLoginPageComponent),
  },
  {
    path: '',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./staff-portal-shell.component').then((m) => m.StaffPortalShellComponent),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./dashboard/my-dashboard.page').then((m) => m.MyDashboardPageComponent),
      },
      {
        path: 'attendance',
        loadComponent: () =>
          import('./attendance/my-attendance.page').then((m) => m.MyAttendancePageComponent),
      },
      {
        path: 'activity',
        loadComponent: () =>
          import('./activity/activity-log.page').then((m) => m.StaffPortalActivityLogPageComponent),
      },
      {
        path: 'sales',
        loadComponent: () => import('./sales/my-sales.page').then((m) => m.MySalesPageComponent),
      },
      {
        path: 'stock',
        loadComponent: () =>
          import('./stock/stock-updates.page').then((m) => m.StockUpdatesPageComponent),
      },
      {
        path: 'field',
        loadComponent: () =>
          import('./field/field-visits.page').then((m) => m.FieldVisitsPageComponent),
      },
    ],
  },
];

import { Routes } from '@angular/router';

import { furnitureAuthGuard } from './core/auth/auth.guard';

export const userRoutes: Routes = [
  {
    path: '',
    canActivate: [furnitureAuthGuard],
    loadComponent: () =>
      import('./core/layout/shell.component').then((m) => m.ShellComponent),
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./layout/welcome.component').then((m) => m.WelcomeComponent),
      },
      {
        path: 'settings',
        loadComponent: () =>
          import('./core/settings/settings-page.component').then(
            (m) => m.SettingsPageComponent,
          ),
      },
    ],
  },
];

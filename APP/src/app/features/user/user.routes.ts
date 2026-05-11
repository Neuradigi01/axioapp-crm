import { Routes } from '@angular/router';

import { furnitureAuthGuard } from './core/auth/auth.guard';

export const userRoutes: Routes = [
  {
    path: '',
    canActivate: [furnitureAuthGuard],
    loadComponent: () =>
      import('./layout/welcome.component').then((m) => m.WelcomeComponent),
  },
];

import { Routes } from '@angular/router';

export const userRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./layout/home-stub.component').then((m) => m.HomeStubComponent),
  },
];

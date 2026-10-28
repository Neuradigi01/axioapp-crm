import { Routes } from '@angular/router';
import { getRoute } from '@core/services/routes-helper.service';

export const setupRoutes: Routes = [
  {
    path: '',
    redirectTo: getRoute('admin_setup_routes').path,
    pathMatch: 'full',
  },
  {
    path: getRoute('admin_setup_routes').path,
    loadComponent: () =>
      import('./routes-manager/routes-manager.component').then(
        (m) => m.RoutesManagerComponent
      ),
  },
  {
    path: getRoute('admin_setup_encryption').path,
    loadComponent: () =>
      import('./encryption/encryption.component').then(
        (m) => m.EncryptionComponent
      ),
  },
];

import { Routes } from '@angular/router';
import { getRoute } from '@core/services/routes-helper.service';

export const subAdminRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./sub-admin-list/sub-admin-list.component').then(
        (m) => m.SubAdminListComponent
      ),
  },
  {
    path: getRoute('add_new_admin').path,
    loadComponent: () =>
      import('./add-sub-admin/add-sub-admin.component').then(
        (m) => m.AddSubAdminComponent
      ),
  },
  {
    path: getRoute('edit_sub_admin').path + '/:id',
    loadComponent: () =>
      import('./edit-sub-admin/edit-sub-admin.component').then(
        (m) => m.EditSubAdminComponent
      ),
  },
  {
    path: getRoute('sub_admin_access_rights').path + '/:id',
    loadComponent: () =>
      import('./access-rights/access-rights.component').then(
        (m) => m.AccessRightsComponent
      ),
  },
];

import { Routes } from '@angular/router';

import { environment } from '../../../environments/environment';
import { furnitureAuthGuard } from './core/auth/auth.guard';

// Dev-only routes are spread into the shell's children when not building
// for production. The guard on the shell still applies, so the route is
// auth-protected even though it has no real backing data.
const devRoutes: Routes = environment.production
  ? []
  : [
      {
        path: 'dev/dynamic-form',
        loadComponent: () =>
          import('./core/shared/dynamic-form/dev-dynamic-form.page').then(
            (m) => m.DevDynamicFormPageComponent,
          ),
      },
      {
        path: 'dev/pipeline-demo',
        loadComponent: () =>
          import('./core/pipelines/dev-pipeline.page').then(
            (m) => m.DevPipelinePageComponent,
          ),
      },
    ];

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
      {
        path: 'contacts',
        loadComponent: () =>
          import('./core/contacts/contacts-list.page').then(
            (m) => m.ContactsListPageComponent,
          ),
      },
      {
        path: 'contacts/:id',
        loadComponent: () =>
          import('./core/contacts/contact-detail.page').then(
            (m) => m.ContactDetailPageComponent,
          ),
      },
      {
        path: 'leads',
        loadComponent: () =>
          import('./core/leads/leads.page').then((m) => m.LeadsPageComponent),
      },
      {
        path: 'appointments',
        loadComponent: () =>
          import('./core/appointments/appointments.page').then(
            (m) => m.AppointmentsPageComponent,
          ),
      },
      {
        path: 'walk-ins',
        loadComponent: () =>
          import('./core/walk-ins/walk-ins.page').then(
            (m) => m.WalkInsPageComponent,
          ),
      },
      {
        path: 'catalog',
        loadComponent: () =>
          import('./core/catalog/catalog.page').then(
            (m) => m.CatalogPageComponent,
          ),
      },
      {
        path: 'staff',
        loadComponent: () =>
          import('./core/staff/staff.page').then(
            (m) => m.StaffPageComponent,
          ),
      },
      ...devRoutes,
    ],
  },
];

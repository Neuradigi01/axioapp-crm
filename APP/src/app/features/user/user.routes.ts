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
      {
        path: 'conversations',
        loadComponent: () =>
          import('./core/conversations/conversations.page').then(
            (m) => m.ConversationsPageComponent,
          ),
      },
      {
        path: 'calls',
        loadComponent: () =>
          import('./core/calls/call-center.page').then(
            (m) => m.CallCenterPageComponent,
          ),
      },
      {
        path: 'reviews',
        loadComponent: () =>
          import('./core/reviews/reviews.page').then(
            (m) => m.ReviewsPageComponent,
          ),
      },
      {
        path: 'campaigns',
        loadComponent: () =>
          import('./core/campaigns/campaigns.page').then(
            (m) => m.CampaignsPageComponent,
          ),
      },
      {
        path: 'campaigns/:id',
        loadComponent: () =>
          import('./core/campaigns/campaign-detail.page').then(
            (m) => m.CampaignDetailPageComponent,
          ),
      },
      {
        path: 'inventory',
        loadComponent: () =>
          import('./packs/furniture/inventory/inventory.page').then(
            (m) => m.InventoryPageComponent,
          ),
      },
      {
        path: 'custom-orders',
        loadComponent: () =>
          import('./packs/furniture/custom-orders/custom-orders.page').then(
            (m) => m.CustomOrdersPageComponent,
          ),
      },
      {
        path: 'custom-orders/:id',
        loadComponent: () =>
          import(
            './packs/furniture/custom-orders/custom-order-detail.page'
          ).then((m) => m.CustomOrderDetailPageComponent),
      },
      {
        path: 'field-ops',
        loadComponent: () =>
          import('./packs/furniture/field-ops/field-ops.page').then(
            (m) => m.FieldOpsPageComponent,
          ),
      },
      {
        path: 'field-ops/:id',
        loadComponent: () =>
          import(
            './packs/furniture/field-ops/field-visit-detail.page'
          ).then((m) => m.FieldVisitDetailPageComponent),
      },
      {
        path: 'billing',
        loadComponent: () =>
          import('./packs/furniture/billing/billing.page').then(
            (m) => m.BillingPageComponent,
          ),
      },
      {
        path: 'billing/invoices/:id',
        loadComponent: () =>
          import(
            './packs/furniture/billing/invoice-detail.page'
          ).then((m) => m.InvoiceDetailPageComponent),
      },
      ...devRoutes,
    ],
  },
];

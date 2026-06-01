import { Routes } from '@angular/router';

import { environment } from '../../../environments/environment';
import { furnitureAuthGuard } from './core/auth/auth.guard';
import { permissionGuard } from './core/auth/permission.guard';

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
        pathMatch: 'full',
        redirectTo: 'dashboard',
      },
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./core/dashboard/dashboard.page').then(
            (m) => m.DashboardPageComponent,
          ),
      },
      {
        path: 'welcome',
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
        // Alias so OAuth callbacks (Google + Meta) can bounce
        // straight to the Integrations tab. The component reads
        // `route.data.tab` to pre-select; existing /user/settings
        // stays on its first-visible tab.
        path: 'settings/integrations',
        data: { tab: 'integrations' },
        loadComponent: () =>
          import('./core/settings/settings-page.component').then(
            (m) => m.SettingsPageComponent,
          ),
      },
      {
        path: 'settings/lead-scoring',
        canActivate: [permissionGuard('leads.scoring.manage')],
        loadComponent: () =>
          import('./core/settings/lead-scoring-rules.page').then(
            (m) => m.LeadScoringRulesPage,
          ),
      },
      {
        path: 'profile',
        loadComponent: () =>
          import('./core/profile/profile-page.component').then(
            (m) => m.ProfilePageComponent,
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
        // MUST precede `contacts/:id` — same reason as the `groups`
        // route below: otherwise `:id` would try to load "import"
        // as a contact UUID.
        path: 'contacts/import',
        canActivate: [permissionGuard('contacts.write')],
        loadComponent: () =>
          import('./core/contacts/imports/import-wizard.page').then(
            (m) => m.ContactImportWizardPageComponent,
          ),
      },
      {
        // MUST precede `contacts/:id` — otherwise the `:id` route
        // would match `/contacts/groups` and try to load it as a
        // contact UUID.
        path: 'contacts/groups',
        loadComponent: () =>
          import('./core/contacts/groups/groups-list.page').then(
            (m) => m.ContactGroupsListPageComponent,
          ),
      },
      {
        path: 'contacts/groups/new',
        loadComponent: () =>
          import('./core/contacts/groups/group-edit.page').then(
            (m) => m.ContactGroupEditPageComponent,
          ),
      },
      {
        path: 'contacts/groups/:id/edit',
        loadComponent: () =>
          import('./core/contacts/groups/group-edit.page').then(
            (m) => m.ContactGroupEditPageComponent,
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
        path: 'leads/import',
        canActivate: [permissionGuard('leads.import')],
        loadComponent: () =>
          import('./core/leads/import/upload-page.component').then(
            (m) => m.UploadPageComponent,
          ),
      },
      {
        path: 'leads/import-history',
        canActivate: [permissionGuard('leads.import')],
        loadComponent: () =>
          import('./core/leads/import/history-page.component').then(
            (m) => m.HistoryPageComponent,
          ),
      },
      {
        path: 'leads/import/:id/mapping',
        canActivate: [permissionGuard('leads.import')],
        loadComponent: () =>
          import('./core/leads/import/mapping-page.component').then(
            (m) => m.MappingPageComponent,
          ),
      },
      {
        path: 'leads/import/:id/result',
        canActivate: [permissionGuard('leads.import')],
        loadComponent: () =>
          import('./core/leads/import/result-page.component').then(
            (m) => m.ResultPageComponent,
          ),
      },
      {
        path: 'appointments',
        loadComponent: () =>
          import('./core/appointments/appointments.page').then(
            (m) => m.AppointmentsPageComponent,
          ),
      },
      {
        path: 'tasks',
        loadComponent: () =>
          import('./core/tasks/tasks.page').then((m) => m.TasksPageComponent),
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
        canActivate: [permissionGuard('staff.read')],
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
        canActivate: [permissionGuard('reviews.read')],
        loadComponent: () =>
          import('./core/reviews/reviews.page').then(
            (m) => m.ReviewsPageComponent,
          ),
      },
      {
        path: 'campaigns',
        canActivate: [permissionGuard('campaigns.read')],
        loadComponent: () =>
          import('./core/campaigns/campaigns.page').then(
            (m) => m.CampaignsPageComponent,
          ),
      },
      {
        path: 'campaigns/:id',
        canActivate: [permissionGuard('campaigns.read')],
        loadComponent: () =>
          import('./core/campaigns/campaign-detail.page').then(
            (m) => m.CampaignDetailPageComponent,
          ),
      },
      {
        path: 'inventory',
        canActivate: [permissionGuard('inventory.read')],
        loadComponent: () =>
          import('./packs/furniture/inventory/inventory.page').then(
            (m) => m.InventoryPageComponent,
          ),
      },
      {
        path: 'custom-orders',
        canActivate: [permissionGuard('custom_orders.read')],
        loadComponent: () =>
          import('./packs/furniture/custom-orders/custom-orders.page').then(
            (m) => m.CustomOrdersPageComponent,
          ),
      },
      {
        path: 'custom-orders/:id',
        canActivate: [permissionGuard('custom_orders.read')],
        loadComponent: () =>
          import(
            './packs/furniture/custom-orders/custom-order-detail.page'
          ).then((m) => m.CustomOrderDetailPageComponent),
      },
      {
        path: 'field-ops',
        canActivate: [permissionGuard('field_visits.read')],
        loadComponent: () =>
          import('./packs/furniture/field-ops/field-ops.page').then(
            (m) => m.FieldOpsPageComponent,
          ),
      },
      {
        path: 'field-ops/:id',
        canActivate: [permissionGuard('field_visits.read')],
        loadComponent: () =>
          import(
            './packs/furniture/field-ops/field-visit-detail.page'
          ).then((m) => m.FieldVisitDetailPageComponent),
      },
      {
        path: 'billing',
        canActivate: [permissionGuard('billing.read')],
        loadComponent: () =>
          import('./packs/furniture/billing/billing.page').then(
            (m) => m.BillingPageComponent,
          ),
      },
      {
        path: 'billing/invoices/:id',
        canActivate: [permissionGuard('billing.read')],
        loadComponent: () =>
          import(
            './packs/furniture/billing/invoice-detail.page'
          ).then((m) => m.InvoiceDetailPageComponent),
      },
      {
        path: 'access-denied',
        loadComponent: () =>
          import('./core/access-denied/access-denied.page').then(
            (m) => m.AccessDeniedPageComponent,
          ),
      },
      ...devRoutes,
    ],
  },
];

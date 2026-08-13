import { Routes } from '@angular/router';

import { environment } from '../../../environments/environment';
import { furnitureAuthGuard } from './core/auth/auth.guard';
import { permissionGuard } from './core/auth/permission.guard';
import { noOrgGuard } from './core/shared/guards/no-org.guard';

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
          import('./core/pipelines/dev-pipeline.page').then((m) => m.DevPipelinePageComponent),
      },
    ];

export const userRoutes: Routes = [
  {
    path: '',
    canActivate: [furnitureAuthGuard],
    // Runs on every child navigation under `/user/*`. Redirects users
    // whose org is still in `template_id="pending"` back to `/onboarding`.
    // Composes with the existing `furnitureAuthGuard` (token check)
    // and the per-route `permissionGuard` (RBAC) — order is:
    // furnitureAuthGuard → noOrgGuard → permissionGuard.
    canActivateChild: [noOrgGuard],
    loadComponent: () => import('./core/layout/shell.component').then((m) => m.ShellComponent),
    children: [
      {
        path: '',
        pathMatch: 'full',
        redirectTo: 'dashboard',
      },
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./core/dashboard/dashboard.page').then((m) => m.DashboardPageComponent),
      },
      {
        path: 'welcome',
        loadComponent: () => import('./layout/welcome.component').then((m) => m.WelcomeComponent),
      },
      {
        path: 'settings',
        loadComponent: () =>
          import('./core/settings/settings-page.component').then((m) => m.SettingsPageComponent),
      },
      {
        // Integrations — promoted to a top-level sidebar module.
        // Open to every role: the page itself renders per-card
        // visibility. Google Calendar (per-user) is always shown so
        // any user can wire their own calendar to receive appointment
        // sync; org-level cards (Google Ads, Meta Ads, WhatsApp, Email)
        // are gated inline by their respective permission keys
        // (`settings.integrations.manage`, `email.accounts.manage`).
        // OAuth callbacks (Google + Meta) and the redirect from the
        // legacy /user/settings/integrations URL both land here.
        path: 'integrations',
        loadComponent: () =>
          import('./core/settings/integrations/integrations-page.component').then(
            (m) => m.IntegrationsPageComponent,
          ),
      },
      {
        // Legacy redirect — Integrations used to live as a tab in
        // /user/settings. OAuth callbacks and old bookmarks still hit
        // this path; bounce them to the new home.
        path: 'settings/integrations',
        redirectTo: '/user/integrations',
        pathMatch: 'full',
      },
      {
        // Legacy alias — the Email Accounts + Sender Setup tabs were
        // consolidated into the per-org Email Sender card on Settings
        // → Integrations. Gmail + Microsoft OAuth `/callback` handlers
        // still redirect here with `?status=…`; forward to the new
        // location preserving the query string.
        path: 'settings/email-accounts',
        redirectTo: '/user/integrations',
        pathMatch: 'full',
      },
      {
        // tasks/template-library Step 10 — the Settings → Email
        // Templates tab moved to the central `/user/templates`
        // library. Three legacy routes (`settings/email-templates`,
        // `/new`, `/:id/edit`) collapsed into a single prefix
        // redirect for muscle-memory bookmarks.
        path: 'settings/email-templates',
        redirectTo: '/user/templates',
        pathMatch: 'prefix',
      },
      {
        // tasks/workflows Step 20 — Email Sequences absorbed into
        // Workflows. The list, builder and detail routes all collapse
        // into a single prefix redirect to the Workflows Marketing
        // category. Old bookmarks land on the Workflows list filtered
        // to Marketing where each migrated sequence appears as a
        // "Sequence: <name>" draft.
        path: 'settings/email-sequences',
        redirectTo: '/user/workflows?category=Marketing',
        pathMatch: 'prefix',
      },
      {
        // SaaS subscription billing — promoted to a top-level sidebar
        // module (manager spec 2026-06-11). Owner-only via the
        // `billing.manage` permission key (Step 19). Stripe Checkout
        // `success_url` / `cancel_url` land on the children below.
        path: 'subscription',
        canActivate: [permissionGuard('billing.manage')],
        loadComponent: () => import('./core/billing/pages/billing.page').then((m) => m.BillingPage),
      },
      {
        // Stripe Checkout `success_url`. Polls `/subscriptions/current`
        // until the webhook flips the row to active, then bounces to
        // `/user/subscription?upgraded=true`.
        path: 'subscription/upgrade-success',
        canActivate: [permissionGuard('billing.manage')],
        loadComponent: () =>
          import('./core/billing/pages/upgrade-success.page').then((m) => m.UpgradeSuccessPage),
      },
      {
        // Stripe Checkout `cancel_url`. Brief page with
        // "Back to Billing" / "Try again" buttons.
        path: 'subscription/upgrade-cancel',
        canActivate: [permissionGuard('billing.manage')],
        loadComponent: () =>
          import('./core/billing/pages/upgrade-cancel.page').then((m) => m.UpgradeCancelPage),
      },
      {
        // Legacy redirects — Billing used to live as a tab in
        // /user/settings. Old bookmarks and in-flight Stripe Checkout
        // sessions still land on these paths until the next cycle
        // boundary; bounce them to the new home.
        path: 'settings/billing',
        redirectTo: '/user/subscription',
        pathMatch: 'full',
      },
      {
        path: 'settings/billing/upgrade-success',
        redirectTo: '/user/subscription/upgrade-success',
        pathMatch: 'full',
      },
      {
        path: 'settings/billing/upgrade-cancel',
        redirectTo: '/user/subscription/upgrade-cancel',
        pathMatch: 'full',
      },
      {
        path: 'settings/lead-scoring',
        canActivate: [permissionGuard('leads.scoring.manage')],
        loadComponent: () =>
          import('./core/settings/lead-scoring-rules.page').then((m) => m.LeadScoringRulesPage),
      },
      {
        // Catalog category taxonomy management. Gated on `catalog.write`
        // — read-only Employees can pick categories in the catalog
        // modal but can't manage the taxonomy.
        path: 'settings/catalog-categories',
        canActivate: [permissionGuard('catalog.write')],
        loadComponent: () =>
          import('./core/settings/catalog-categories.page').then(
            (m) => m.CatalogCategoriesPageComponent,
          ),
      },
      {
        // E.16 / F1 — Lead routing config. Backend endpoints are
        // gated on `settings.read` / `settings.write`; the guard here
        // uses `settings.write` so read-only Admins can still land on
        // the page but the save action 403s.
        path: 'settings/lead-routing',
        canActivate: [permissionGuard('settings.write')],
        loadComponent: () =>
          import('./core/settings/lead-routing.page').then((m) => m.LeadRoutingPage),
      },
      {
        // Fold-in redirect: the standalone /user/profile page was
        // removed when its UI moved into Settings → Profile tab.
        // Existing bookmarks / deep links land on the same surface.
        path: 'profile',
        redirectTo: '/user/settings?tab=profile',
        pathMatch: 'full',
      },
      {
        path: 'contacts',
        loadComponent: () =>
          import('./core/contacts/contacts-list.page').then((m) => m.ContactsListPageComponent),
      },
      {
        // MUST precede `contacts/:id` — same reason as the `groups`
        // route below: otherwise `:id` would try to load "import"
        // as a contact UUID. The `/history` child MUST come before
        // the parent `import` for the same static-vs-param reason.
        path: 'contacts/import/history',
        canActivate: [permissionGuard('contacts.write')],
        loadComponent: () =>
          import('./core/contacts/imports/import-history.page').then(
            (m) => m.ContactImportHistoryPageComponent,
          ),
      },
      {
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
          import('./core/contacts/contact-detail.page').then((m) => m.ContactDetailPageComponent),
      },
      {
        path: 'leads',
        loadComponent: () => import('./core/leads/leads.page').then((m) => m.LeadsPageComponent),
      },
      {
        path: 'leads/import',
        canActivate: [permissionGuard('leads.import')],
        loadComponent: () =>
          import('./core/leads/import/upload-page.component').then((m) => m.UploadPageComponent),
      },
      {
        path: 'leads/import-history',
        canActivate: [permissionGuard('leads.import')],
        loadComponent: () =>
          import('./core/leads/import/history-page.component').then((m) => m.HistoryPageComponent),
      },
      {
        path: 'leads/import/:id/mapping',
        canActivate: [permissionGuard('leads.import')],
        loadComponent: () =>
          import('./core/leads/import/mapping-page.component').then((m) => m.MappingPageComponent),
      },
      {
        path: 'leads/import/:id/result',
        canActivate: [permissionGuard('leads.import')],
        loadComponent: () =>
          import('./core/leads/import/result-page.component').then((m) => m.ResultPageComponent),
      },
      {
        // MUST come after every literal `leads/...` path above —
        // otherwise `:id` swallows `leads/import`, `leads/import-history`,
        // etc. and the import flow never resolves.
        path: 'leads/:id',
        loadComponent: () =>
          import('./core/leads/lead-detail.page').then((m) => m.LeadDetailPageComponent),
      },
      {
        path: 'appointments',
        loadComponent: () =>
          import('./core/appointments/appointments.page').then((m) => m.AppointmentsPageComponent),
      },
      {
        path: 'tasks',
        loadComponent: () => import('./core/tasks/tasks.page').then((m) => m.TasksPageComponent),
      },
      {
        path: 'walk-ins',
        loadComponent: () =>
          import('./core/walk-ins/walk-ins.page').then((m) => m.WalkInsPageComponent),
      },
      {
        // MUST precede `catalog/:id` if that route is ever added
        // (same reason as `contacts/import`) — the wizard is a static
        // segment.
        path: 'catalog/import',
        canActivate: [permissionGuard('catalog.write')],
        loadComponent: () =>
          import('./core/catalog/import/bulk-import.page').then(
            (m) => m.CatalogBulkImportPageComponent,
          ),
      },
      {
        path: 'catalog',
        loadComponent: () =>
          import('./core/catalog/catalog.page').then((m) => m.CatalogPageComponent),
      },
      {
        path: 'staff',
        canActivate: [permissionGuard('staff.read')],
        loadComponent: () => import('./core/staff/staff.page').then((m) => m.StaffPageComponent),
      },
      {
        path: 'conversations',
        loadComponent: () =>
          import('./core/conversations/conversations.page').then(
            (m) => m.ConversationsPageComponent,
          ),
      },
      {
        // whatsapp-platform-upgrade Step 9 — template builder UI.
        // Read-gated; write + submit affordances inside are hidden
        // per-role by the page component (junior sales sees the
        // table but no Create / Edit / Submit buttons).
        path: 'whatsapp/templates',
        canActivate: [permissionGuard('whatsapp.templates.read')],
        loadComponent: () =>
          import('./core/whatsapp/templates/whatsapp-templates.page').then(
            (m) => m.WhatsAppTemplatesPageComponent,
          ),
      },
      {
        // tasks/template-library Step 6 — central multi-channel template
        // library list page. Read-gated; "New template" + per-row
        // workflow buttons are hidden per-role inside the page itself
        // (Employee sees the table; Owner/Admin see write affordances).
        path: 'templates',
        canActivate: [permissionGuard('templates.read')],
        loadComponent: () =>
          import('./core/templates/templates.page').then((m) => m.TemplatesPageComponent),
      },
      {
        // tasks/workflows Step 13 — workflow list + folders + run
        // history drawer. Read-gated; "New workflow" + bulk
        // activate / pause / archive affordances inside the page
        // hide for read-only Employees via the runtime permission
        // check. Step 14 ships the canvas editor at /:id; Step 16
        // the templates gallery at /new.
        path: 'workflows',
        canActivate: [permissionGuard('workflows.read')],
        loadComponent: () =>
          import('./core/workflows/workflows.page').then((m) => m.WorkflowsPageComponent),
      },
      {
        // tasks/chatbot-builder Step 12 — chatbots list page. Sidebar
        // entry is auto-registered by backend `core.chatbots.module.py`
        // (Step 3); this route is what the sidebar item links to.
        // Builder page + node editors land in Steps 13-14.
        path: 'chatbots',
        canActivate: [permissionGuard('chatbots.view')],
        loadComponent: () =>
          import('./core/chatbots/list/chatbots-list.page').then(
            (m) => m.ChatbotsListPageComponent,
          ),
      },
      {
        // tasks/chatbot-builder Step 13 — Pabbly-style bot builder
        // canvas. Write-gated because every interaction implies a
        // mutation; read-only Employees land on the list page and
        // see disabled "Edit" affordances there.
        path: 'chatbots/:id/edit',
        canActivate: [permissionGuard('chatbots.edit')],
        loadComponent: () =>
          import('./core/chatbots/builder/builder.page').then((m) => m.ChatbotBuilderPageComponent),
      },
      {
        // tasks/workflows Step 16 — gallery of 15 default workflow
        // templates. Read-gated; the "Use this template" CTA inside
        // the page needs `workflows.clone` server-side, but the
        // gallery is browse-friendly to read-only employees.
        path: 'workflows/gallery',
        canActivate: [permissionGuard('workflows.read')],
        loadComponent: () =>
          import('./core/workflows/gallery/workflows-gallery.page').then(
            (m) => m.WorkflowsGalleryPageComponent,
          ),
      },
      {
        // tasks/workflows Step 14 — SVG canvas editor. /new boots a
        // fresh draft; /:id loads the existing workflow. Write-gated
        // because every interaction (drag-drop, save, activate)
        // implies a mutation; read-only users land on the list page
        // instead.
        path: 'workflows/new',
        canActivate: [permissionGuard('workflows.write')],
        loadComponent: () =>
          import('./core/workflows/canvas/workflow-canvas.page').then(
            (m) => m.WorkflowCanvasPageComponent,
          ),
      },
      {
        // tasks/workflows Step 19 — "why didn't this fire?" diagnostics.
        // MUST precede `workflows/:id` so `:id` doesn't swallow
        // `diagnostics`. Gated on `workflows.view_diagnostics` (Owner
        // / Admin only by default).
        path: 'workflows/diagnostics',
        canActivate: [permissionGuard('workflows.view_diagnostics')],
        loadComponent: () =>
          import('./core/workflows/diagnostics/diagnostics.page').then(
            (m) => m.WorkflowDiagnosticsPageComponent,
          ),
      },
      {
        // tasks/workflows Step 19 — per-run timeline. MUST precede
        // `workflows/:id` so `:id` doesn't swallow `runs`.
        path: 'workflows/runs/:run_id',
        canActivate: [permissionGuard('workflows.read')],
        loadComponent: () =>
          import('./core/workflows/run-detail.page').then((m) => m.WorkflowRunDetailPageComponent),
      },
      {
        // tasks/workflows Step 19 — per-workflow analytics dashboard.
        // MUST precede `workflows/:id`.
        path: 'workflows/:id/analytics',
        canActivate: [permissionGuard('workflows.view_analytics')],
        loadComponent: () =>
          import('./core/workflows/analytics/workflow-analytics.page').then(
            (m) => m.WorkflowAnalyticsPageComponent,
          ),
      },
      {
        // tasks/workflows Step 18 — full-page side-by-side A/B
        // comparison. MUST precede `workflows/:id` so `:id` doesn't
        // swallow `ab-compare`.
        path: 'workflows/:id/ab-compare',
        canActivate: [permissionGuard('workflows.read')],
        loadComponent: () =>
          import('./core/workflows/ab/ab-comparison.page').then((m) => m.ABComparisonPageComponent),
      },
      {
        path: 'workflows/:id',
        canActivate: [permissionGuard('workflows.read')],
        loadComponent: () =>
          import('./core/workflows/canvas/workflow-canvas.page').then(
            (m) => m.WorkflowCanvasPageComponent,
          ),
      },
      {
        // tasks/workflows-absorb-automation Step 3 — the Automations
        // module was absorbed into Workflows on 2026-08-05. The
        // sidebar entry is hidden (module.py: menu_position=None) and
        // every legacy /user/automations/* URL redirects into the
        // Workflows page. The old feature components under
        // ./core/automations/ are RETAINED, per the manager directive
        // "do not delete or remove its code", but no route in this
        // table loads them anymore. Step-1's data migration wrote
        // `tbl_automation_triggers.migrated_to_workflow_id` for every
        // pre-cutover trigger; the RedirectAutomationComponent reads
        // that FK to preserve deep-link bookmarks.
        path: 'automations',
        redirectTo: '/user/workflows',
        pathMatch: 'full',
      },
      {
        path: 'automations/new',
        redirectTo: '/user/workflows/new',
        pathMatch: 'full',
      },
      {
        // Deep-link resolver — reads the FK via the endpoint added
        // in Step 3 and navigates to the matching workflow's canvas,
        // or falls back to the workflows list.
        path: 'automations/:id',
        loadComponent: () =>
          import('./core/workflows/redirect-automation.component').then(
            (m) => m.RedirectAutomationComponent,
          ),
      },
      {
        // Legacy run-history URLs — no per-run ID mapping to workflow
        // runs (the two engines wrote to separate audit tables). Bounce
        // to the workflows list so operators can find the workflow
        // manually.
        path: 'automations/:id/runs',
        redirectTo: '/user/workflows',
        pathMatch: 'full',
      },
      {
        // tasks/template-library Step 7 — channel-aware editor.
        // `/new` for create, `/:id` for edit. Save / save-and-submit
        // affordances inside are gated on `templates.write` —
        // Employee sees a read-only editor.
        path: 'templates/new',
        canActivate: [permissionGuard('templates.read')],
        loadComponent: () =>
          import('./core/templates/editor/template-editor.page').then(
            (m) => m.TemplateEditorPageComponent,
          ),
      },
      {
        path: 'templates/:id',
        canActivate: [permissionGuard('templates.read')],
        loadComponent: () =>
          import('./core/templates/editor/template-editor.page').then(
            (m) => m.TemplateEditorPageComponent,
          ),
      },
      {
        // whatsapp-platform-upgrade Step 11 — business profile editor.
        // Single permission key gates the whole page (the editor is
        // admin-grade — junior roles get no useful read-only view).
        path: 'whatsapp/business-profile',
        canActivate: [permissionGuard('whatsapp.business_profile.manage')],
        loadComponent: () =>
          import('./core/whatsapp/business-profile/business-profile.page').then(
            (m) => m.WhatsAppBusinessProfilePageComponent,
          ),
      },
      {
        // whatsapp-platform-upgrade Step 17 — keyword automation rules.
        // Future Step 18 (auto-assignment) + Step 19 (AI agent) will
        // tab into this same page.
        path: 'whatsapp/automation',
        canActivate: [permissionGuard('whatsapp.automation.manage')],
        loadComponent: () =>
          import('./core/whatsapp/automation/automation.page').then(
            (m) => m.WhatsAppAutomationPageComponent,
          ),
      },
      {
        // whatsapp-platform-upgrade Step 23 — block list (DND).
        // Gated on `whatsapp.opt_in.manage` so Owner + Admin manage
        // it but junior staff don't see the surface.
        path: 'whatsapp/block-list',
        canActivate: [permissionGuard('whatsapp.opt_in.manage')],
        loadComponent: () =>
          import('./core/whatsapp/block-list/block-list-page.component').then(
            (m) => m.BlockListPageComponent,
          ),
      },
      {
        // whatsapp-platform-upgrade Step 25 — WhatsApp Flows library.
        // Gated on `whatsapp.flows.manage` (Owner / Admin by default).
        path: 'whatsapp/flows',
        canActivate: [permissionGuard('whatsapp.flows.manage')],
        loadComponent: () =>
          import('./core/whatsapp/flows/flows-page.component').then(
            (m) => m.WhatsAppFlowsPageComponent,
          ),
      },
      {
        // whatsapp-platform-upgrade Step 26 — QR + wa.me tracking links.
        // Reuses `whatsapp.automation.manage` per the step spec.
        path: 'whatsapp/quick-links',
        canActivate: [permissionGuard('whatsapp.automation.manage')],
        loadComponent: () =>
          import('./core/whatsapp/quick-links/quick-links-page.component').then(
            (m) => m.WhatsAppQuickLinksPageComponent,
          ),
      },
      {
        path: 'calls',
        loadComponent: () =>
          import('./core/calls/call-center.page').then((m) => m.CallCenterPageComponent),
      },
      {
        // whatsapp-platform-upgrade Step 20 — conversation analytics
        // dashboard. Gated on `whatsapp.analytics.read`; sidebar entry
        // surfaces via the reporting module descriptor.
        path: 'reports/whatsapp',
        canActivate: [permissionGuard('whatsapp.analytics.read')],
        loadComponent: () =>
          import('./core/reporting/whatsapp/whatsapp-reports-page.component').then(
            (m) => m.WhatsAppReportsPageComponent,
          ),
      },
      {
        path: 'reviews',
        canActivate: [permissionGuard('reviews.read')],
        loadComponent: () =>
          import('./core/reviews/reviews.page').then((m) => m.ReviewsPageComponent),
      },
      {
        path: 'campaigns',
        canActivate: [permissionGuard('campaigns.read')],
        loadComponent: () =>
          import('./core/campaigns/campaigns.page').then((m) => m.CampaignsPageComponent),
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
          import('./packs/furniture/custom-orders/custom-order-detail.page').then(
            (m) => m.CustomOrderDetailPageComponent,
          ),
      },
      {
        path: 'field-ops',
        canActivate: [permissionGuard('field_visits.read')],
        loadComponent: () =>
          import('./packs/furniture/field-ops/field-ops.page').then((m) => m.FieldOpsPageComponent),
      },
      {
        path: 'field-ops/:id',
        canActivate: [permissionGuard('field_visits.read')],
        loadComponent: () =>
          import('./packs/furniture/field-ops/field-visit-detail.page').then(
            (m) => m.FieldVisitDetailPageComponent,
          ),
      },
      {
        path: 'billing',
        canActivate: [permissionGuard('billing.read')],
        loadComponent: () =>
          import('./packs/furniture/billing/billing.page').then((m) => m.BillingPageComponent),
      },
      {
        path: 'billing/invoices/:id',
        canActivate: [permissionGuard('billing.read')],
        loadComponent: () =>
          import('./packs/furniture/billing/invoice-detail.page').then(
            (m) => m.InvoiceDetailPageComponent,
          ),
      },
      {
        path: 'properties',
        canActivate: [permissionGuard('property.read')],
        loadComponent: () =>
          import('./packs/real_estate/property/property-list.page').then(
            (m) => m.PropertyListPageComponent,
          ),
      },
      {
        path: 'properties/new',
        canActivate: [permissionGuard('property.write')],
        loadComponent: () =>
          import('./packs/real_estate/property/property-form.page').then(
            (m) => m.PropertyFormPageComponent,
          ),
      },
      {
        path: 'properties/:id/edit',
        canActivate: [permissionGuard('property.write')],
        loadComponent: () =>
          import('./packs/real_estate/property/property-form.page').then(
            (m) => m.PropertyFormPageComponent,
          ),
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

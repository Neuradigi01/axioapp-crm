# FurnitureCRM — Page-to-Table Map

Reference document mapping every UI page to the database tables it reads from or writes to. Generated from `APP/src/app/...` routes and `API/src/app/core/**/models.py` + `API/src/app/packs/furniture/modules/**/models.py`.

**Legend:** Tables prefixed `tbl_*` are legacy auth schema. `fp_*` are furniture-pack tables. `core/*` paths are Layer 1 (universal CRM). `packs/furniture/*` are Layer 2 (vertical pack).

---

## 1. Authentication & Account Pages

Base: `/accounts` — [APP/src/app/features/accounts/accounts.routes.ts](APP/src/app/features/accounts/accounts.routes.ts)

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Login** | `/accounts/login` | `LoginComponent` | `tbl_user_login`, `tbl_user_info`, `tbl_organization_members`, `auth_sessions`, `organizations`, `roles` |
| **Admin Login** | `/accounts/admin_login` | `LoginComponent` (Admin variant) | `tbl_user_login`, `tbl_user_info`, `tbl_organization_members`, `auth_sessions` |
| **Register** | `/accounts/register` | `RegisterComponent` | `tbl_user_login`, `tbl_user_info`, `tbl_organization_members`, `organizations`, `roles`, `permissions` |
| **Forgot Password** | `/accounts/forgot_password` | `ForgotPasswordComponent` | `tbl_user_login`, `tbl_user_info` |
| **Reset Password** | `/accounts/reset_password` | `ResetPasswordComponent` | `tbl_user_login` |
| **2FA Challenge** | `/accounts/two_factor_authentication` | `TwoFactorComponent` | `tbl_user_login`, `auth_sessions` |
| **Verify Email** | `/accounts/verify_email` | `VerifyEmailComponent` | `tbl_user_info` |
| **Email Verification Notice** | `/accounts/email_verification_notice` | `EmailVerificationNoticeComponent` | `tbl_user_info` |
| **Accept Invite** | `/accounts/accept-invite?token=...` | `AcceptInviteComponent` | `invitations`, `tbl_user_login`, `tbl_user_info`, `tbl_organization_members`, `roles` |

---

## 2. Core CRM Pages

Base: `/user` — [APP/src/app/features/user/user.routes.ts](APP/src/app/features/user/user.routes.ts)

### 2.1 Dashboard

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Dashboard** | `/user/dashboard` | `DashboardPageComponent` | `leads`, `walk_ins`, `appointments`, `tasks`, `contacts`, `campaigns`, `conversations`, `calls`, `invoices`, `staff_profiles`, `attendance`, `activities`, `custom_field_definitions`, `pipelines`, `pipeline_stages` |
| **Welcome** | `/user/welcome` | `WelcomeComponent` | `contacts`, `leads`, `walk_ins`, `pipelines`, `pipeline_stages` |

### 2.2 Contacts

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Contacts List** | `/user/contacts` | `ContactsListPageComponent` | `contacts`, `activities`, `custom_field_definitions`, `leads`, `walk_ins`, `appointments` |
| **Contact Detail** | `/user/contacts/:id` | `ContactDetailPageComponent` | `contacts`, `activities`, `leads`, `walk_ins`, `appointments`, `tasks`, `calls`, `conversations`, `reviews`, `custom_field_definitions`, `staff_profiles` |
| **Contact Import Wizard** | `/user/contacts/import` | `ContactImportWizardPageComponent` | `contact_imports`, `contacts`, `custom_field_definitions`, `import_presets` |
| **Contact Groups List** | `/user/contacts/groups` | `ContactGroupsListPageComponent` | `contact_groups`, `custom_field_definitions` |
| **Contact Group Editor** | `/user/contacts/groups/new`, `/user/contacts/groups/:id/edit` | `ContactGroupEditPageComponent` | `contact_groups`, `contact_group_members`, `contacts` |

### 2.3 Leads

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Leads (Kanban)** | `/user/leads` | `LeadsPageComponent` | `leads`, `contacts`, `pipelines`, `pipeline_stages`, `activities`, `custom_field_definitions`, `lead_scoring_rules` |
| **Lead Import — Upload** | `/user/leads/import` | `UploadPageComponent` | `lead_imports` |
| **Lead Import — History** | `/user/leads/import-history` | `HistoryPageComponent` | `lead_imports` |
| **Lead Import — Mapping** | `/user/leads/import/:id/mapping` | `MappingPageComponent` | `lead_imports`, `custom_field_definitions`, `import_presets` |
| **Lead Import — Result** | `/user/leads/import/:id/result` | `ResultPageComponent` | `lead_imports`, `leads`, `contacts` |

### 2.4 Walk-Ins

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Walk-Ins** | `/user/walk-ins` | `WalkInsPageComponent` | `walk_ins`, `contacts`, `activities`, `custom_field_definitions`, `leads`, `staff_profiles` |

### 2.5 Appointments

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Appointments Calendar** | `/user/appointments` | `AppointmentsPageComponent` | `appointments`, `contacts`, `activities`, `custom_field_definitions`, `staff_profiles` |

### 2.6 Tasks

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Tasks** | `/user/tasks` | `TasksPageComponent` | `tasks`, `contacts`, `leads`, `walk_ins`, `appointments`, `activities`, `custom_field_definitions`, `staff_profiles` |

### 2.7 Conversations (Inbox)

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Conversations** | `/user/conversations` | `ConversationsPageComponent` | `conversations`, `messages`, `contacts`, `activities`, `custom_field_definitions`, `integrations`, `whatsapp_account_configs`, `whatsapp_templates` |

### 2.8 Calls

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Call Center** | `/user/calls` | `CallCenterPageComponent` | `calls`, `call_transcripts`, `call_outcomes`, `contacts`, `activities`, `custom_field_definitions`, `staff_profiles` |

### 2.9 Reviews

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Reviews** | `/user/reviews` | `ReviewsPageComponent` | `reviews`, `contacts`, `activities`, `custom_field_definitions` |

### 2.10 Campaigns

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Campaigns List** | `/user/campaigns` | `CampaignsPageComponent` | `campaigns`, `campaign_messages`, `contacts`, `whatsapp_templates`, `conversations`, `messages` |
| **Campaign Detail** | `/user/campaigns/:id` | `CampaignDetailPageComponent` | `campaigns`, `campaign_messages`, `contacts`, `whatsapp_templates` |

### 2.11 Catalog

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Catalog (Products)** | `/user/catalog` | `CatalogPageComponent` | `catalog_items`, `custom_field_definitions`, `fp_inventory_items` |

### 2.12 Staff

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Staff List** | `/user/staff` | `StaffPageComponent` | `staff_profiles`, `tbl_user_login`, `tbl_user_info`, `tbl_organization_members`, `attendance`, `roles`, `permissions` |

### 2.13 Profile & Settings

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **User Profile** | `/user/profile` | `ProfilePageComponent` | `tbl_user_info`, `tbl_organization_members`, `staff_profiles`, `roles` |
| **Settings (Main)** | `/user/settings` | `SettingsPageComponent` | `org_settings`, `custom_field_definitions`, `roles`, `permissions`, `staff_profiles`, `integrations`, `whatsapp_account_configs`, `conversations`, `pipelines`, `pipeline_stages`, `standard_field_overrides` |
| **Settings → Integrations** | `/user/settings/integrations` | `SettingsPageComponent` | `integrations`, `meta_page_tokens`, `whatsapp_account_configs`, `whatsapp_templates`, `integration_subscriptions`, `integration_dlq` |

### 2.14 Reporting

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Reporting** | `/user/reporting` | `ReportingComponent` | `leads`, `walk_ins`, `appointments`, `calls`, `invoices`, `activities`, `contacts`, `staff_profiles`, `attendance`, `campaigns`, `campaign_messages` |

### 2.15 Misc

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Access Denied** | `/user/access-denied` | `AccessDeniedPageComponent` | (none) |

---

## 3. Furniture Pack Pages

Base: `/user` — [APP/src/app/features/user/packs/furniture/](APP/src/app/features/user/packs/furniture/)

### 3.1 Inventory

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Inventory** | `/user/inventory` | `InventoryPageComponent` | `fp_warehouses`, `fp_inventory_items`, `fp_inventory_movements`, `fp_inventory_alerts`, `catalog_items`, `custom_field_definitions` |

### 3.2 Custom Orders

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Custom Orders List** | `/user/custom-orders` | `CustomOrdersPageComponent` | `fp_custom_orders`, `contacts`, `leads`, `pipelines`, `pipeline_stages`, `activities`, `custom_field_definitions`, `staff_profiles` |
| **Custom Order Detail** | `/user/custom-orders/:id` | `CustomOrderDetailPageComponent` | `fp_custom_orders`, `fp_custom_order_measurements`, `fp_custom_order_photos`, `fp_custom_order_stages`, `fp_field_visits`, `contacts`, `leads`, `activities`, `appointments`, `staff_profiles`, `custom_field_definitions` |

### 3.3 Field Operations

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Field Visits List** | `/user/field-ops` | `FieldOpsPageComponent` | `fp_field_visits`, `appointments`, `fp_custom_orders`, `contacts`, `activities`, `custom_field_definitions`, `staff_profiles` |
| **Field Visit Detail** | `/user/field-ops/:id` | `FieldVisitDetailPageComponent` | `fp_field_visits`, `fp_field_visit_photos`, `appointments`, `fp_custom_orders`, `contacts`, `activities`, `staff_profiles`, `custom_field_definitions` |

### 3.4 Billing

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Billing (Invoices)** | `/user/billing` | `BillingPageComponent` | `invoices`, `invoice_lines`, `payments`, `contacts`, `catalog_items`, `org_invoice_seq`, `custom_field_definitions` |
| **Invoice Detail** | `/user/billing/invoices/:id` | `InvoiceDetailPageComponent` | `invoices`, `invoice_lines`, `payments`, `contacts`, `catalog_items` |

---

## 4. Staff Portal (Tablet)

Base: `/staff-portal` — [APP/src/app/staff-portal/staff-portal.routes.ts](APP/src/app/staff-portal/staff-portal.routes.ts)

| Page | URL | Component | Tables Touched |
|------|-----|-----------|----------------|
| **Staff PIN Login** | `/staff-portal/login` | `StaffPortalLoginPageComponent` | `tbl_user_login`, `staff_profiles`, `staff_sessions`, `tbl_organization_members` |
| **My Dashboard** | `/staff-portal/dashboard` | `MyDashboardPageComponent` | `staff_profiles`, `attendance`, `walk_ins`, `appointments`, `tasks`, `fp_custom_orders`, `fp_field_visits`, `activities` |
| **My Attendance** | `/staff-portal/attendance` | `MyAttendancePageComponent` | `attendance`, `staff_profiles` |
| **Activity Log** | `/staff-portal/activity` | `StaffPortalActivityLogPageComponent` | `activities`, `contacts`, `leads`, `walk_ins`, `appointments` |
| **My Sales** | `/staff-portal/sales` | `MySalesPageComponent` | `leads`, `walk_ins`, `contacts`, `invoices`, `activities`, `staff_profiles` |
| **Stock Updates** | `/staff-portal/stock` | `StockUpdatesPageComponent` | `fp_inventory_items`, `fp_inventory_movements`, `fp_warehouses`, `catalog_items` |
| **Field Visits** | `/staff-portal/field` | `FieldVisitsPageComponent` | `fp_field_visits`, `fp_field_visit_photos`, `appointments`, `fp_custom_orders`, `contacts`, `activities` |

---

## 5. Legacy Admin Pages (Untouched in FurnitureCRM)

Base: `/admin` — [APP/src/app/features/admin/admin.routes.ts](APP/src/app/features/admin/admin.routes.ts)

> These pages belong to the legacy template's admin panel. They are kept working (login still routes to `/admin/dashboard`) but are NOT part of FurnitureCRM. Do not modify.

| Page | URL | Tables Touched |
|------|-----|----------------|
| Admin Dashboard | `/admin/dashboard` | `tbl_user_login`, `organizations`, `tbl_organization_members` |
| Admin Profile | `/admin/profile` | `tbl_user_login`, `tbl_user_info` |
| Admin Security | `/admin/security` | `tbl_user_login`, `auth_sessions` |
| Change Password | `/admin/change_password` | `tbl_user_login` |
| Login History | `/admin/login_history` | `auth_sessions`, `audit_logs` |
| Member Search | `/admin/member-controls/search` | `tbl_user_login`, `tbl_user_info`, `tbl_organization_members`, `roles` |
| Member Profile | `/admin/member-controls/profile/:id` | `tbl_user_login`, `tbl_user_info`, `tbl_organization_members`, `roles`, `permissions` |
| Sub-Admin Management | `/admin/sub-admin/*` | `tbl_user_login`, `tbl_user_info`, `organizations`, `roles` |
| Support — Compose / Tickets / View | `/admin/support/...` | legacy support tables |
| News / Popups / Newsletter / Contact Us | `/admin/news`, `/admin/popups`, `/admin/newsletter`, `/admin/contact_us` | legacy content tables |
| Routes Manager / Encryption | `/admin/setup/routes`, `/admin/setup/encryption` | legacy config tables |

---

## 6. Database Table Reference

### 6.1 Legacy Auth Schema (preserved from template)

| Table | Model | File |
|-------|-------|------|
| `tbl_user_login` | `User` | [API/src/app/core/users/models.py](API/src/app/core/users/models.py) |
| `tbl_user_info` | `UserInfo` | [API/src/models/user.py](API/src/models/user.py) |
| `tbl_organization_members` | `OrganizationMember` | [API/src/app/core/users/models.py](API/src/app/core/users/models.py) |
| `users` (shim for FK) | — | [API/src/app/core/users/models.py](API/src/app/core/users/models.py) |
| `auth_sessions` | `AuthSession` | [API/src/app/core/auth/models.py](API/src/app/core/auth/models.py) |
| `staff_sessions` | `StaffSession` | [API/src/app/core/staff_portal/models.py](API/src/app/core/staff_portal/models.py) |

### 6.2 Tenants, Roles, Permissions

| Table | Model | File |
|-------|-------|------|
| `organizations` | `Organization` | [API/src/app/core/tenants/models.py](API/src/app/core/tenants/models.py) |
| `roles` | `Role` | [API/src/app/core/permissions/models.py](API/src/app/core/permissions/models.py) |
| `permissions` | `Permission` | [API/src/app/core/permissions/models.py](API/src/app/core/permissions/models.py) |
| `role_permissions` | `RolePermission` | [API/src/app/core/permissions/models.py](API/src/app/core/permissions/models.py) |
| `invitations` | `Invitation` | [API/src/app/core/invitations/models.py](API/src/app/core/invitations/models.py) |

### 6.3 Core CRM Domain

| Table | Model | File |
|-------|-------|------|
| `contacts` | `Contact` | [API/src/app/core/contacts/models.py](API/src/app/core/contacts/models.py) |
| `contact_groups` | `ContactGroup` | [API/src/app/core/contacts/groups/models.py](API/src/app/core/contacts/groups/models.py) |
| `contact_group_members` | `ContactGroupMember` | [API/src/app/core/contacts/groups/models.py](API/src/app/core/contacts/groups/models.py) |
| `contact_imports` | `ContactImport` | [API/src/app/core/contacts/imports/models.py](API/src/app/core/contacts/imports/models.py) |
| `leads` | `Lead` | [API/src/app/core/leads/models.py](API/src/app/core/leads/models.py) |
| `lead_scoring_rules` | `LeadScoringRule` | [API/src/app/core/leads/models.py](API/src/app/core/leads/models.py) |
| `lead_imports` | `LeadImport` | [API/src/app/core/leads/imports/models.py](API/src/app/core/leads/imports/models.py) |
| `import_presets` | `ImportPreset` | [API/src/app/core/leads/imports/models.py](API/src/app/core/leads/imports/models.py) |
| `lead_sources` | `LeadSource` | [API/src/app/core/packs/models.py](API/src/app/core/packs/models.py) |
| `pipelines` | `Pipeline` | [API/src/app/core/pipelines/models.py](API/src/app/core/pipelines/models.py) |
| `pipeline_stages` | `PipelineStage` | [API/src/app/core/pipelines/models.py](API/src/app/core/pipelines/models.py) |
| `walk_ins` | `WalkIn` | [API/src/app/core/walk_ins/models.py](API/src/app/core/walk_ins/models.py) |
| `appointments` | `Appointment` | [API/src/app/core/appointments/models.py](API/src/app/core/appointments/models.py) |
| `tasks` | `Task` | [API/src/app/core/tasks/models.py](API/src/app/core/tasks/models.py) |
| `activities` | `Activity` | [API/src/app/core/activities/models.py](API/src/app/core/activities/models.py) |

### 6.4 Communications

| Table | Model | File |
|-------|-------|------|
| `conversations` | `Conversation` | [API/src/app/core/conversations/models.py](API/src/app/core/conversations/models.py) |
| `messages` | `Message` | [API/src/app/core/conversations/models.py](API/src/app/core/conversations/models.py) |
| `calls` | `Call` | [API/src/app/core/calls/models.py](API/src/app/core/calls/models.py) |
| `call_transcripts` | `CallTranscript` | [API/src/app/core/calls/models.py](API/src/app/core/calls/models.py) |
| `call_outcomes` | `CallOutcome` | [API/src/app/core/calls/models.py](API/src/app/core/calls/models.py) |
| `reviews` | `Review` | [API/src/app/core/reviews/models.py](API/src/app/core/reviews/models.py) |
| `campaigns` | `Campaign` | [API/src/app/core/campaigns/models.py](API/src/app/core/campaigns/models.py) |
| `campaign_messages` | `CampaignMessage` | [API/src/app/core/campaigns/models.py](API/src/app/core/campaigns/models.py) |

### 6.5 Catalog, Billing, Staff

| Table | Model | File |
|-------|-------|------|
| `catalog_items` | `CatalogItem` | [API/src/app/core/catalog/models.py](API/src/app/core/catalog/models.py) |
| `invoices` | `Invoice` | [API/src/app/core/billing/models.py](API/src/app/core/billing/models.py) |
| `invoice_lines` | `InvoiceLine` | [API/src/app/core/billing/models.py](API/src/app/core/billing/models.py) |
| `payments` | `Payment` | [API/src/app/core/billing/models.py](API/src/app/core/billing/models.py) |
| `org_invoice_seq` | `OrgInvoiceSeq` | [API/src/app/core/billing/models.py](API/src/app/core/billing/models.py) |
| `staff_profiles` | `StaffProfile` | [API/src/app/core/staff/models.py](API/src/app/core/staff/models.py) |
| `attendance` | `Attendance` | [API/src/app/core/staff/models.py](API/src/app/core/staff/models.py) |

### 6.6 Settings, Custom Fields, Integrations

| Table | Model | File |
|-------|-------|------|
| `org_settings` | `OrgSettings` | [API/src/app/core/settings/models.py](API/src/app/core/settings/models.py) |
| `custom_field_definitions` | `CustomFieldDefinition` | [API/src/app/core/custom_fields/models.py](API/src/app/core/custom_fields/models.py) |
| `standard_field_overrides` | `StandardFieldOverride` | [API/src/app/core/standard_fields/models.py](API/src/app/core/standard_fields/models.py) |
| `integrations` | `Integration` | [API/src/app/core/integrations/models.py](API/src/app/core/integrations/models.py) |
| `integration_subscriptions` | `IntegrationSubscription` | [API/src/app/core/integrations/models.py](API/src/app/core/integrations/models.py) |
| `integration_dlq` | `IntegrationDLQ` | [API/src/app/core/integrations/models.py](API/src/app/core/integrations/models.py) |
| `meta_page_tokens` | `MetaPageToken` | [API/src/app/core/integrations/meta/models.py](API/src/app/core/integrations/meta/models.py) |
| `whatsapp_account_configs` | `WhatsAppAccountConfig` | [API/src/app/core/integrations/whatsapp/models.py](API/src/app/core/integrations/whatsapp/models.py) |
| `whatsapp_templates` | `WhatsAppTemplate` | [API/src/app/core/integrations/whatsapp/models.py](API/src/app/core/integrations/whatsapp/models.py) |
| `notifications` | `Notification` | [API/src/app/core/notifications/models.py](API/src/app/core/notifications/models.py) |
| `notification_preferences` | `NotificationPreference` | [API/src/app/core/notifications/models.py](API/src/app/core/notifications/models.py) |
| `audit_logs` | `AuditLog` | [API/src/app/core/audit/models.py](API/src/app/core/audit/models.py) |
| `embed_keys` | `EmbedKey` | [API/src/app/core/embed/models.py](API/src/app/core/embed/models.py) |
| `widget_configs` | `WidgetConfig` | [API/src/app/core/embed/models.py](API/src/app/core/embed/models.py) |
| `embed_submissions` | `EmbedSubmission` | [API/src/app/core/embed/models.py](API/src/app/core/embed/models.py) |
| `demo_credentials` | `DemoCredential` | [API/src/app/core/dev/models.py](API/src/app/core/dev/models.py) |

### 6.7 Furniture Pack Tables (Layer 2)

| Table | Model | File |
|-------|-------|------|
| `fp_warehouses` | `Warehouse` | [API/src/app/packs/furniture/modules/inventory/models.py](API/src/app/packs/furniture/modules/inventory/models.py) |
| `fp_inventory_items` | `InventoryItem` | [API/src/app/packs/furniture/modules/inventory/models.py](API/src/app/packs/furniture/modules/inventory/models.py) |
| `fp_inventory_movements` | `InventoryMovement` | [API/src/app/packs/furniture/modules/inventory/models.py](API/src/app/packs/furniture/modules/inventory/models.py) |
| `fp_inventory_alerts` | `StockAlert` | [API/src/app/packs/furniture/modules/inventory/models.py](API/src/app/packs/furniture/modules/inventory/models.py) |
| `fp_custom_orders` | `CustomOrder` | [API/src/app/packs/furniture/modules/custom_orders/models.py](API/src/app/packs/furniture/modules/custom_orders/models.py) |
| `fp_custom_order_measurements` | `CustomOrderMeasurement` | [API/src/app/packs/furniture/modules/custom_orders/models.py](API/src/app/packs/furniture/modules/custom_orders/models.py) |
| `fp_custom_order_photos` | `CustomOrderPhoto` | [API/src/app/packs/furniture/modules/custom_orders/models.py](API/src/app/packs/furniture/modules/custom_orders/models.py) |
| `fp_custom_order_stages` | `CustomOrderStageHistory` | [API/src/app/packs/furniture/modules/custom_orders/models.py](API/src/app/packs/furniture/modules/custom_orders/models.py) |
| `fp_field_visits` | `FieldVisit` | [API/src/app/packs/furniture/modules/field_ops/models.py](API/src/app/packs/furniture/modules/field_ops/models.py) |
| `fp_field_visit_photos` | `FieldVisitPhoto` | [API/src/app/packs/furniture/modules/field_ops/models.py](API/src/app/packs/furniture/modules/field_ops/models.py) |

---

## 7. Architectural Notes

- **Multi-tenancy:** every tenant-scoped table has `org_id` and is protected by Postgres RLS. The `organizations` table is the tenant root.
- **3-table user identity:** auth (`tbl_user_login`) + profile (`tbl_user_info`) + membership (`tbl_organization_members`) — one auth user can belong to multiple orgs with different roles.
- **Activities timeline:** the `activities` table is universal — every entity (contact, lead, walk_in, call, task, ...) writes timeline events here via polymorphic `entity_type` + `entity_id`. Many entities also denormalize `last_activity_at` for fast sort.
- **Custom fields:** values live in a `custom_data` JSONB column on each entity; definitions live in `custom_field_definitions` keyed by `(entity_type, field_key)`. The `source` column tags each definition as `system` | `pack` | `user`.
- **Pipelines:** kanban stages are referenced by their text `key` (immutable) — not by UUID — so re-seeding pack defaults doesn't orphan records.
- **Sequences:** invoice numbers are issued atomically via `org_invoice_seq.last_number` (one row per org).
- **Sessions:** admin/JWT sessions in `auth_sessions`; staff PIN tablet sessions in `staff_sessions` (4-hour TTL).

---

**Totals:** ~50 user-facing pages mapping to ~60 database tables across `core` (Layer 1) and `packs/furniture` (Layer 2).

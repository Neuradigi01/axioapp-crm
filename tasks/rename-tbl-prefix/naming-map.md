# Naming map — `tbl_` prefix standardisation

Single source of truth for what gets renamed to what across the rename-`tbl_`-prefix track. Generated from a read-only audit of `api/src/` on 2026-06-12.

**Status: Awaiting decision on Option A vs Option B for `fp_*` furniture-pack tables (last section).**

---

## 0. Headline numbers

| Bucket | Count | Action |
|---|---:|---|
| Legacy template (`API/src/models/*`), already `tbl_*` | 22 | **No rename.** Already canonical. |
| Layered core (`api/src/app/core/*`), already `tbl_*` | 2 | **No rename.** `tbl_user_login`, `tbl_organization_members`. |
| Layered core, plain-named — needs rename | **67** | Step 2 (models + FK) + Step 3 (migration). |
| Furniture pack (`api/src/app/packs/furniture/*`), `fp_*` | 10 | **Awaiting A/B decision.** |
| Test-sandbox tables in `api/tests/` | 2 | Excluded — never deployed (`_test_tenant_thing`, `_test_paginate_rows`). |
| Metadata shim (no physical table) | 1 | `users` shim — delete the shim Table in Step 2; retarget the FKs that reference it. |

**Total rename count: 67 tables, plus 10 furniture-pack tables pending A/B decision.**

Verification command (Windows PowerShell):

```powershell
(Select-String -Path "API\src\app\**\*.py" -Pattern '__tablename__\s*=\s*"[a-z]').Count
```

Expected: **77** matches (67 plain core + 10 `fp_*`). If your count differs, a model file landed between this audit and Step 2 — fold it in before proceeding.

---

## 1. Layered core — needs rename (67 tables)

| Current name | → | Proposed new name | Source file | RLS? |
|---|---|---|---|---:|
| activities | → | tbl_activities | [`API/src/app/core/activities/models.py:56`](API/src/app/core/activities/models.py#L56) | ✓ |
| appointments | → | tbl_appointments | [`API/src/app/core/appointments/models.py:53`](API/src/app/core/appointments/models.py#L53) | ✓ |
| attendance | → | tbl_attendance | [`API/src/app/core/staff/models.py:91`](API/src/app/core/staff/models.py#L91) | ✓ |
| audit_logs | → | tbl_audit_logs | [`API/src/app/core/audit/models.py:24`](API/src/app/core/audit/models.py#L24) | ✓ |
| auth_sessions | → | tbl_auth_sessions | [`API/src/app/core/auth/models.py:27`](API/src/app/core/auth/models.py#L27) | ✓ |
| calls | → | tbl_calls | [`API/src/app/core/calls/models.py:84`](API/src/app/core/calls/models.py#L84) | ✓ |
| call_outcomes | → | tbl_call_outcomes | [`API/src/app/core/calls/models.py:58`](API/src/app/core/calls/models.py#L58) | ✓ |
| call_transcripts | → | tbl_call_transcripts | [`API/src/app/core/calls/models.py:136`](API/src/app/core/calls/models.py#L136) | ✓ |
| campaigns | → | tbl_campaigns | [`API/src/app/core/campaigns/models.py:77`](API/src/app/core/campaigns/models.py#L77) | ✓ |
| campaign_messages | → | tbl_campaign_messages | [`API/src/app/core/campaigns/models.py:143`](API/src/app/core/campaigns/models.py#L143) | ✓ |
| catalog_items | → | tbl_catalog_items | [`API/src/app/core/catalog/models.py:37`](API/src/app/core/catalog/models.py#L37) | ✓ |
| contacts | → | tbl_contacts | [`API/src/app/core/contacts/models.py:35`](API/src/app/core/contacts/models.py#L35) | ✓ |
| contact_groups | → | tbl_contact_groups | [`API/src/app/core/contacts/groups/models.py:32`](API/src/app/core/contacts/groups/models.py#L32) | ✓ |
| contact_group_members | → | tbl_contact_group_members | [`API/src/app/core/contacts/groups/models.py:70`](API/src/app/core/contacts/groups/models.py#L70) | ✓ |
| contact_imports | → | tbl_contact_imports | [`API/src/app/core/contacts/imports/models.py:33`](API/src/app/core/contacts/imports/models.py#L33) | ✓ |
| conversations | → | tbl_conversations | [`API/src/app/core/conversations/models.py:83`](API/src/app/core/conversations/models.py#L83) | ✓ |
| custom_field_definitions | → | tbl_custom_field_definitions | [`API/src/app/core/custom_fields/models.py:79`](API/src/app/core/custom_fields/models.py#L79) | ✓ |
| demo_credentials | → | tbl_demo_credentials | [`API/src/app/core/dev/models.py:22`](API/src/app/core/dev/models.py#L22) | dev-only |
| email_accounts | → | tbl_email_accounts | [`API/src/app/core/email/models.py:72`](API/src/app/core/email/models.py#L72) | ✓ |
| email_message_clicks | → | tbl_email_message_clicks | [`API/src/app/core/email/tracking/models.py:51`](API/src/app/core/email/tracking/models.py#L51) | ✓ |
| email_message_opens | → | tbl_email_message_opens | [`API/src/app/core/email/tracking/models.py:29`](API/src/app/core/email/tracking/models.py#L29) | ✓ |
| email_sequences | → | tbl_email_sequences | [`API/src/app/core/email_sequences/models.py:69`](API/src/app/core/email_sequences/models.py#L69) | ✓ |
| email_sequence_steps | → | tbl_email_sequence_steps | [`API/src/app/core/email_sequences/models.py:104`](API/src/app/core/email_sequences/models.py#L104) | ✓ |
| email_sequence_enrollments | → | tbl_email_sequence_enrollments | [`API/src/app/core/email_sequences/models.py:129`](API/src/app/core/email_sequences/models.py#L129) | ✓ |
| email_sequence_enrollment_steps | → | tbl_email_sequence_enrollment_steps | [`API/src/app/core/email_sequences/models.py:184`](API/src/app/core/email_sequences/models.py#L184) | ✓ |
| email_templates | → | tbl_email_templates | [`API/src/app/core/email_templates/models.py:30`](API/src/app/core/email_templates/models.py#L30) | ✓ |
| embed_keys | → | tbl_embed_keys | [`API/src/app/core/embed/models.py:28`](API/src/app/core/embed/models.py#L28) | ✓ |
| embed_submissions | → | tbl_embed_submissions | [`API/src/app/core/embed/models.py:133`](API/src/app/core/embed/models.py#L133) | ✓ |
| import_presets | → | tbl_import_presets | [`API/src/app/core/leads/imports/models.py:109`](API/src/app/core/leads/imports/models.py#L109) | ✓ (custom policy — see §5) |
| integrations | → | tbl_integrations | [`API/src/app/core/integrations/models.py:64`](API/src/app/core/integrations/models.py#L64) | ✓ |
| integration_subscriptions | → | tbl_integration_subscriptions | [`API/src/app/core/integrations/models.py:156`](API/src/app/core/integrations/models.py#L156) | ✓ |
| integration_dlq | → | tbl_integration_dlq | [`API/src/app/core/integrations/models.py:205`](API/src/app/core/integrations/models.py#L205) | ✓ |
| invitations | → | tbl_invitations | [`API/src/app/core/invitations/models.py:27`](API/src/app/core/invitations/models.py#L27) | ✓ |
| invoices | → | tbl_invoices | [`API/src/app/core/billing/models.py:79`](API/src/app/core/billing/models.py#L79) | ✓ |
| invoice_lines | → | tbl_invoice_lines | [`API/src/app/core/billing/models.py:155`](API/src/app/core/billing/models.py#L155) | ✓ |
| leads | → | tbl_leads | [`API/src/app/core/leads/models.py:80`](API/src/app/core/leads/models.py#L80) | ✓ |
| lead_imports | → | tbl_lead_imports | [`API/src/app/core/leads/imports/models.py:58`](API/src/app/core/leads/imports/models.py#L58) | ✓ |
| lead_routing_state | → | tbl_lead_routing_state | _no model — created in [`API/alembic/versions/0051_routing_and_dedup.py:76`](API/alembic/versions/0051_routing_and_dedup.py#L76); only referenced via raw SQL in [`core/leads/routing.py:149`](API/src/app/core/leads/routing.py#L149)_ | ✓ |
| lead_scoring_rules | → | tbl_lead_scoring_rules | [`API/src/app/core/leads/models.py:174`](API/src/app/core/leads/models.py#L174) | ✓ |
| lead_sources | → | tbl_lead_sources | [`API/src/app/core/packs/models.py:32`](API/src/app/core/packs/models.py#L32) | ✓ |
| messages | → | tbl_messages | [`API/src/app/core/conversations/models.py:137`](API/src/app/core/conversations/models.py#L137) | ✓ |
| meta_page_tokens | → | tbl_meta_page_tokens | [`API/src/app/core/integrations/meta/models.py:33`](API/src/app/core/integrations/meta/models.py#L33) | ✓ |
| notifications | → | **tbl_crm_notifications** ⚠ | [`API/src/app/core/notifications/models.py:54`](API/src/app/core/notifications/models.py#L54) | ✓ |
| notification_preferences | → | tbl_notification_preferences | [`API/src/app/core/notifications/models.py:92`](API/src/app/core/notifications/models.py#L92) | ✓ |
| organizations | → | tbl_organizations | [`API/src/app/core/tenants/models.py:22`](API/src/app/core/tenants/models.py#L22) | ✓ (column=id) |
| org_invoice_seq | → | tbl_org_invoice_seq | [`API/src/app/core/billing/models.py:241`](API/src/app/core/billing/models.py#L241) | ✓ |
| org_settings | → | tbl_org_settings | [`API/src/app/core/settings/models.py:37`](API/src/app/core/settings/models.py#L37) | ✓ |
| payments | → | tbl_payments | [`API/src/app/core/billing/models.py:195`](API/src/app/core/billing/models.py#L195) | ✓ |
| permissions | → | tbl_permissions | [`API/src/app/core/permissions/models.py:49`](API/src/app/core/permissions/models.py#L49) | global registry — verify RLS |
| pipelines | → | tbl_pipelines | [`API/src/app/core/pipelines/models.py:42`](API/src/app/core/pipelines/models.py#L42) | ✓ |
| pipeline_stages | → | tbl_pipeline_stages | [`API/src/app/core/pipelines/models.py:69`](API/src/app/core/pipelines/models.py#L69) | inherits from pipelines |
| reviews | → | tbl_reviews | [`API/src/app/core/reviews/models.py:53`](API/src/app/core/reviews/models.py#L53) | ✓ |
| roles | → | tbl_roles | [`API/src/app/core/permissions/models.py:29`](API/src/app/core/permissions/models.py#L29) | ✓ |
| role_permissions | → | tbl_role_permissions | [`API/src/app/core/permissions/models.py:65`](API/src/app/core/permissions/models.py#L65) | inherits from roles |
| saved_views | → | tbl_saved_views | [`API/src/app/core/saved_views/models.py:42`](API/src/app/core/saved_views/models.py#L42) | ✓ |
| staff_profiles | → | tbl_staff_profiles | [`API/src/app/core/staff/models.py:54`](API/src/app/core/staff/models.py#L54) | ✓ |
| staff_sessions | → | tbl_staff_sessions | [`API/src/app/core/staff_portal/models.py:25`](API/src/app/core/staff_portal/models.py#L25) | ✓ |
| standard_field_overrides | → | tbl_standard_field_overrides | [`API/src/app/core/standard_fields/models.py:37`](API/src/app/core/standard_fields/models.py#L37) | ✓ |
| stripe_webhook_events | → | tbl_stripe_webhook_events | [`API/src/app/core/subscriptions/models.py:411`](API/src/app/core/subscriptions/models.py#L411) | global — Stripe-id keyed |
| subscriptions | → | tbl_subscriptions | [`API/src/app/core/subscriptions/models.py:78`](API/src/app/core/subscriptions/models.py#L78) | ✓ |
| subscription_invoices | → | tbl_subscription_invoices | [`API/src/app/core/subscriptions/models.py:336`](API/src/app/core/subscriptions/models.py#L336) | ✓ |
| tasks | → | tbl_tasks | [`API/src/app/core/tasks/models.py:56`](API/src/app/core/tasks/models.py#L56) | ✓ |
| usage_counters | → | tbl_usage_counters | [`API/src/app/core/subscriptions/models.py:259`](API/src/app/core/subscriptions/models.py#L259) | ✓ |
| walk_ins | → | tbl_walk_ins | [`API/src/app/core/walk_ins/models.py:59`](API/src/app/core/walk_ins/models.py#L59) | ✓ |
| whatsapp_account_configs | → | tbl_whatsapp_account_configs | [`API/src/app/core/integrations/whatsapp/models.py:45`](API/src/app/core/integrations/whatsapp/models.py#L45) | ✓ |
| whatsapp_templates | → | tbl_whatsapp_templates | [`API/src/app/core/integrations/whatsapp/models.py:101`](API/src/app/core/integrations/whatsapp/models.py#L101) | ✓ |
| widget_configs | → | tbl_widget_configs | [`API/src/app/core/embed/models.py:77`](API/src/app/core/embed/models.py#L77) | ✓ |

**67 rows.** RLS check column = whether the table calls `apply_rls(...)` in any migration (confirmed against `Grep` of `API/alembic/versions/`). The 40-table RLS impact set is enumerated in §5.

### ⚠ Name collision — `notifications`

The legacy template owns `tbl_notifications` ([`API/src/models/notification.py:9`](API/src/models/notification.py#L9)) — push notifications for the legacy admin panel. Per [CLAUDE.md](CLAUDE.md), `features/admin/` is UNTOUCHED indefinitely; that includes its tables. Renaming core's `notifications` directly to `tbl_notifications` would collide.

**Resolution:** core's `notifications` → **`tbl_crm_notifications`** (only deviation from the otherwise-mechanical `tbl_<existing>` rule). Captures the conceptual scope (in-app CRM notifications, distinct from legacy push). Sibling table `notification_preferences` → `tbl_notification_preferences` does NOT collide; it stays mechanical.

If you'd rather use a different unique name (`tbl_app_notifications`, `tbl_user_notifications`, etc.), call it out before Step 2 starts.

---

## 2. Already-canonical core tables — **no rename**

These already use `tbl_*` (shipped by DR.6 / DR.7 — the three-table user split). Step 2 does NOT touch them.

| Name | Source |
|---|---|
| tbl_user_login | [`API/src/app/core/users/models.py:92`](API/src/app/core/users/models.py#L92) (also legacy-mapped at [`API/src/models/user.py:9`](API/src/models/user.py#L9)) |
| tbl_organization_members | [`API/src/app/core/users/models.py:244`](API/src/app/core/users/models.py#L244) |

---

## 3. Legacy template tables — **no rename, no touch**

22 tables in `API/src/models/*`, all already `tbl_*` and serving the legacy admin panel. Per [CLAUDE.md](CLAUDE.md), this code path is UNTOUCHED indefinitely.

`tbl_admin`, `tbl_admin_routes`, `tbl_contact_us`, `tbl_countries`, `tbl_device_tokens`, `tbl_error_logs`, `tbl_login_history`, `tbl_news`, `tbl_newsletter`, `tbl_notifications`, `tbl_otp_requests`, `tbl_password_change_history`, `tbl_password_reset_tokens`, `tbl_popups`, `tbl_profile_change_history`, `tbl_routes`, `tbl_states`, `tbl_ticket_attachments`, `tbl_ticket_replies`, `tbl_tickets`, `tbl_used_action_tokens`, `tbl_user_info`, `tbl_user_login`.

(Note: `tbl_user_info` and `tbl_user_login` are physical tables shared with the layered package — already canonical from DR.6/DR.7.)

---

## 4. Furniture pack — **awaiting A/B decision**

10 tables in `api/src/app/packs/furniture/*`. Decision below.

| Current | Option A (recommended) | Option B |
|---|---|---|
| fp_warehouses | tbl_fp_warehouses | fp_warehouses (no change) |
| fp_inventory_items | tbl_fp_inventory_items | fp_inventory_items |
| fp_inventory_movements | tbl_fp_inventory_movements | fp_inventory_movements |
| fp_inventory_alerts | tbl_fp_inventory_alerts | fp_inventory_alerts |
| fp_field_visits | tbl_fp_field_visits | fp_field_visits |
| fp_field_visit_photos | tbl_fp_field_visit_photos | fp_field_visit_photos |
| fp_custom_orders | tbl_fp_custom_orders | fp_custom_orders |
| fp_custom_order_measurements | tbl_fp_custom_order_measurements | fp_custom_order_measurements |
| fp_custom_order_photos | tbl_fp_custom_order_photos | fp_custom_order_photos |
| fp_custom_order_stages | tbl_fp_custom_order_stages | fp_custom_order_stages |

See §10 for the decision recommendation.

---

## 5. RLS-bound tables — Step 3 must rebuild policies on every one of these

From `Grep` of `apply_rls(...)` across `API/alembic/versions/`. 40 calls total.

```
organizations (column=id)         contacts                 lead_routing_state
roles                             walk_ins                 saved_views
users  ← see §8: physical table   call_outcomes            lead_scoring_rules
auth_sessions                     calls                    subscriptions
audit_logs                        call_transcripts         usage_counters
custom_field_definitions          conversations            subscription_invoices
activities                        messages                 email_accounts
tasks                             reviews                  email_templates
pipelines                         campaigns                email_sequences
pipeline_stages                   campaign_messages        email_sequence_steps
leads                             org_settings             email_sequence_enrollments
appointments                      catalog_items            email_sequence_enrollment_steps
notifications                     embed_keys               email_message_opens
notification_preferences          embed_submissions        email_message_clicks
staff_profiles                    widget_configs           import_presets ← custom policies
attendance                        integrations             contact_groups
staff_sessions                    integration_subscriptions contact_group_members
invitations                       integration_dlq          contact_imports
invoices                          meta_page_tokens         standard_field_overrides
invoice_lines                     whatsapp_account_configs
payments                          whatsapp_templates
org_invoice_seq (column=org_id)   fp_warehouses
                                  fp_inventory_items
                                  fp_inventory_movements
                                  fp_inventory_alerts
                                  fp_custom_orders
                                  fp_custom_order_measurements
                                  fp_custom_order_photos
                                  fp_custom_order_stages
                                  fp_field_visits
                                  fp_field_visit_photos
```

**Special cases for Step 3:**

- **`organizations`** — `apply_rls("organizations", column="id")` — policy uses `id`, not `org_id`. Re-emit with the same kwarg on `tbl_organizations`.
- **`org_invoice_seq`** — `apply_rls("org_invoice_seq", column="org_id")` — explicit kwarg per [`0028_billing.py:267`](API/alembic/versions/0028_billing.py#L267). Re-emit with the kwarg on `tbl_org_invoice_seq`.
- **`import_presets`** — uses custom `import_presets_read` (`FOR SELECT`) + `import_presets_write` (`FOR ALL`) policies, NOT the generic `apply_rls()` helper. See [`0042_import_presets.py:108-135`](API/alembic/versions/0042_import_presets.py#L108). Step 3 must hand-emit these two policies against `tbl_import_presets`, not call the helper.
- **`users`** — see §8 below. The migration `0003` issued `apply_rls("users")`, then migration `0037` dropped the table. Don't include `tbl_users` in Step 3's rename loop.

---

## 6. ForeignKey reference map — Step 2 must update every one of these

From `Grep` for `ForeignKey("…")` across `api/src/app/`. 50 references in 24 files. Targets that need updating:

| Target | Refs | Notes |
|---|---:|---|
| contacts.id | 9 | Highest-FK target. Becomes `tbl_contacts.id`. |
| integrations.id | 5 | Becomes `tbl_integrations.id`. |
| fp_custom_orders.id | 3 | Subject to A/B decision. |
| organizations.id | 3 | Becomes `tbl_organizations.id`. |
| roles.id | 3 | Becomes `tbl_roles.id`. |
| leads.id | 3 | Becomes `tbl_leads.id`. |
| invoices.id | 2 | Becomes `tbl_invoices.id`. |
| fp_inventory_items.id | 2 | Subject to A/B decision. |
| fp_warehouses.id | 1 | Subject to A/B decision. |
| fp_field_visits.id | 1 | Subject to A/B decision. |
| appointments.id | 1 | Becomes `tbl_appointments.id`. |
| call_outcomes.id | 1 | Becomes `tbl_call_outcomes.id`. |
| calls.id | 1 | Becomes `tbl_calls.id`. |
| campaigns.id | 1 | Becomes `tbl_campaigns.id`. |
| catalog_items.id | 1 | Becomes `tbl_catalog_items.id`. |
| contact_groups.id | 2 | Becomes `tbl_contact_groups.id`. |
| conversations.id | 1 | Becomes `tbl_conversations.id`. |
| permissions.id | 1 | Becomes `tbl_permissions.id`. |
| whatsapp_templates.id | 1 | Becomes `tbl_whatsapp_templates.id`. |
| pipelines.id | 1 | Becomes `tbl_pipelines.id`. |
| **users.id** | **2** | **See §8.** Pre-existing dangling FK — physical table dropped by 0037. |
| **tbl_user_login.id** | **1** | Already canonical (DR.6) — no change. |

Total updates in Step 2: **47 FK strings** (50 total minus 1 already-canonical minus 2 `users.id` flagged separately).

---

## 7. Raw-SQL touch points — Step 4 must update every literal

From `Grep` for `FROM/JOIN/INSERT/UPDATE/DELETE <name>` in `text(...)` blocks across `API/src/`. Excludes Alembic versions (historical, do not edit).

| File | Old reference | Becomes |
|---|---|---|
| [`API/src/app/core/campaigns/tasks.py:122,186`](API/src/app/core/campaigns/tasks.py) | `FROM campaigns` | `FROM tbl_campaigns` |
| [`API/src/app/core/email/gmail/push.py:151`](API/src/app/core/email/gmail/push.py) | `FROM email_accounts` | `FROM tbl_email_accounts` |
| [`API/src/app/core/email/service.py:109`](API/src/app/core/email/service.py) | `FROM email_accounts` | `FROM tbl_email_accounts` |
| [`API/src/app/core/email/tasks.py:382,430`](API/src/app/core/email/tasks.py) | `FROM email_accounts` | `FROM tbl_email_accounts` |
| [`API/src/app/core/email/microsoft/webhook.py:243`](API/src/app/core/email/microsoft/webhook.py) | `FROM email_accounts` | `FROM tbl_email_accounts` |
| [`API/src/app/core/email/tracking/router.py:141,232`](API/src/app/core/email/tracking/router.py) | `FROM messages` | `FROM tbl_messages` |
| [`API/src/app/core/leads/imports/dedup.py:74`](API/src/app/core/leads/imports/dedup.py) | `FROM contacts` | `FROM tbl_contacts` |
| [`API/src/app/core/leads/dedup.py:67`](API/src/app/core/leads/dedup.py) | `FROM leads` | `FROM tbl_leads` |
| [`API/src/app/core/integrations/service.py:274`](API/src/app/core/integrations/service.py) | `FROM integrations` | `FROM tbl_integrations` |
| [`API/src/app/core/integrations/status.py:124`](API/src/app/core/integrations/status.py) | `FROM audit_logs` | `FROM tbl_audit_logs` |
| [`API/src/app/core/integrations/google/tasks.py:439,481`](API/src/app/core/integrations/google/tasks.py) | `FROM integrations`, `FROM leads` | `tbl_*` |
| [`API/src/app/core/integrations/meta/tasks.py:468`](API/src/app/core/integrations/meta/tasks.py) | `FROM leads` | `FROM tbl_leads` |
| [`API/src/app/core/subscriptions/lifecycle.py:165`](API/src/app/core/subscriptions/lifecycle.py) | `DELETE FROM subscriptions` | `DELETE FROM tbl_subscriptions` |
| [`API/src/app/core/subscriptions/usage_service.py:158,232,267`](API/src/app/core/subscriptions/usage_service.py) | `INSERT INTO usage_counters` | `INSERT INTO tbl_usage_counters` |
| [`API/src/app/core/leads/routing.py:149`](API/src/app/core/leads/routing.py) | `INSERT INTO lead_routing_state` | `INSERT INTO tbl_lead_routing_state` |
| [`API/src/app/scripts/seed_contact_system_fields.py:48`](API/src/app/scripts/seed_contact_system_fields.py) | `INSERT INTO custom_field_definitions` | `INSERT INTO tbl_custom_field_definitions` |
| [`API/src/app/scripts/seed_call_outcomes.py:41`](API/src/app/scripts/seed_call_outcomes.py) | `INSERT INTO call_outcomes` | `INSERT INTO tbl_call_outcomes` |

**~17 distinct file-line edits across ~14 files** in Step 4. Plus the seed-script sweep below.

### Seed scripts to audit in Step 4

All under [`API/src/app/scripts/`](API/src/app/scripts/):

- `install_pack.py` — pack installer; may have literal table refs.
- `seed_admin_user.py` — admin user seed; check.
- `seed_call_outcomes.py` — has `INSERT INTO call_outcomes`. Update.
- `seed_contact_system_fields.py` — has `INSERT INTO custom_field_definitions`. Update.
- `seed_core_demo_org.py` — demo-org seed; check.
- `seed_demo_org.py` — older demo seed; check.
- `seed_stripe_catalog.py` — Stripe plan seed; check.
- `backfill_integrations_permission.py` — permission backfill; check.

---

## 8. The `users` shim — pre-existing tech debt, flagged but parked

History from `Grep` of `API/alembic/versions/`:

1. Migration [`0003_users_roles_permissions.py:60`](API/alembic/versions/0003_users_roles_permissions.py#L60) creates the `users` table.
2. DR.6 / migrations 0032–0037 introduce `tbl_user_login` + drop `users.id` FKs.
3. Migration `0037_drop_users_id_fks.py`, `0062_drop_core_users_id_fks.py`, `0063_drop_pack_users_id_fks.py` retarget the FK COLUMNS that point at `users.id` — but the `ForeignKey("users.id")` strings in model code still appear in:
   - [`API/src/app/core/audit/models.py:33`](API/src/app/core/audit/models.py#L33) — `ForeignKey("users.id", ondelete="SET NULL")` on `audit_logs.user_id`
   - [`API/src/app/core/auth/models.py:36`](API/src/app/core/auth/models.py#L36) — `ForeignKey("users.id", ondelete="CASCADE")` on `auth_sessions.user_id`
4. [`API/src/app/core/users/models.py:83-88`](API/src/app/core/users/models.py#L83-L88) declares a metadata-only `Table("users", Base.metadata, Column("id", UUID(as_uuid=True), primary_key=True), extend_existing=True)` shim **just so the FK strings above resolve at MetaData time**. Comment in the source says "we'll retarget those FKs and drop this shim once the soak completes."

**This track inherits the shim, doesn't fix it.** Reason: retargeting `audit_logs.user_id` and `auth_sessions.user_id` from `users.id` (UUID) to either `tbl_user_login.id` (BIGINT — incompatible type) or `tbl_user_login.legacy_uuid` (UUID — requires a separate migration to populate or rename the column) is a substantive refactor with type-conversion implications. Out of scope for a pure prefix rename.

**Action in Step 2:**

- Leave the shim `Table("users", …)` as-is.
- Leave `ForeignKey("users.id")` strings as-is. They do NOT participate in the rename.
- The shim's table name `"users"` does NOT get prefixed (it's not a real table; it's a metadata placeholder).

**Action in Step 3:**

- Don't include `users` in the rename loop (table doesn't exist on disk).
- Don't re-emit RLS on `users` (the `0003`'s `apply_rls("users")` is reversed by the same physical drop chain).

**Follow-up suggested (NEW track, not this one):** retarget those two FKs to `tbl_user_login.legacy_uuid` and drop the shim. Pure cleanup; no data implications.

---

## 9. Test-sandbox tables — excluded

| Name | File | Why excluded |
|---|---|---|
| `_test_tenant_thing` | [`API/tests/test_tenant_filter.py:42`](API/tests/test_tenant_filter.py#L42) | Created per-test via `Base.metadata.create_all`, dropped at teardown. Never lives in prod. |
| `_test_paginate_rows` | [`API/tests/test_pagination.py:30`](API/tests/test_pagination.py#L30) | Same. |

Step 5's pin-test will explicitly allow names starting with `_test_`.

---

## 10. Decision needed — Option A vs Option B for `fp_*`

### Option A — unify (recommended)

Every furniture-pack table gets prefixed: `fp_warehouses` → **`tbl_fp_warehouses`**, etc.

- ✅ Single convention rule across the entire schema. SQL audits, schema dumps, and grep workflows all key on `tbl_%`.
- ✅ Pack origin still readable from the middle segment (`tbl_fp_*`).
- ✅ Matches the [`API/docs/DATABASE_RULES.md:24`](API/docs/DATABASE_RULES.md#L24) rule literally.
- ✅ Future packs (if a second vertical pack ever lands) would also adopt `tbl_<pack>_*`, keeping the rule consistent.
- ⚠ More tables to touch in this track — 10 extra renames in Step 3.

### Option B — keep `fp_*` as a parallel prefix

Furniture-pack tables stay `fp_*`. Only the 67 core tables become `tbl_*`.

- ✅ Smaller change set for this track.
- ✅ Pack origin remains a top-level visual marker.
- ❌ Two coexisting conventions forever. SQL audits cannot pattern-match application tables with a single rule.
- ❌ A future pack would face the same decision again, and inconsistency compounds.
- ❌ Doesn't strictly match the documented `DATABASE_RULES.md` rule.

### Recommendation: **Option A**.

The whole point of this track is to make ONE rule. Allowing `fp_*` to stand as a second rule undermines that. The 10 extra renames are trivial inside the same migration. Step 2 references to `fp_*` (4 FKs in pack models, 4 raw-SQL refs in pack tasks) are already in scope.

---

## Awaiting decision

**Reply with "proceed with A" or "proceed with B" to start Step 2.**

If you spot anything in this map you want changed before Step 2 starts (alternative name for `notifications`, a table I missed, a rename you disagree with), call it out now — adjustments after Step 2 begins mean recoding the rewrite.

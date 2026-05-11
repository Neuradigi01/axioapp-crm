# Step 4.2 — Apply furniture pack to demo org

**Goal:** Write the actual `furniture/pack.yaml` reflecting the screenshots: pipeline stages, custom fields, roles, lead sources, call outcomes, currency INR, tax 18%, AI defaults. Run installer on the seeded demo org. Verify the existing UI now reflects furniture defaults.
**Phase:** 4
**Depends on:** 4.1
**Status:** Pending

## Scope
**In-scope:**
- `api/src/app/packs/furniture/pack.yaml` containing:
  - `pipelines.leads`: New → Contacted → Showroom Visit → Quotation → Won (is_won) / Lost (is_lost).
  - `pipelines.custom_orders`: Measurement Scheduled → Design Phase → In Production → QC → Installation → Delivered.
  - `custom_fields.contact`: budget_range (select), preferred_material (select), room_type (select), requirement (text).
  - `custom_fields.lead`: budget_range (select), preferred_material, room_type, expected_visit_date (date).
  - `custom_fields.walk_in`: requirement (text), product_interest_id (foreign-ref to catalog), budget_range (select).
  - `roles`: Owner, Store Manager, Senior Sales Executive, Sales Executive, Junior Sales Executive, Design Consultant, Warehouse Manager — each with sensible permissions.
  - `lead_sources`: WhatsApp, Instagram, Facebook, Website, Walk-in, Reference, Marketplace.
  - `call_outcomes`: Appointment Booked, Quote Sent, Showroom Visit Scheduled, Not Interested, Callback Requested, Wrong Number.
  - `defaults`: currency=INR, tax_rate=18.00, timezone=Asia/Kolkata, review_source=google.
  - `ai`: personality (helpful furniture sales assistant), welcome_message ("Hi! Welcome to <store>. How can I help?"), follow_up_schedule (Day 1, Day 3, Day 7 with templates).
- Run installer on demo org.
- Verify: `GET /pipelines/leads` returns 5 stages, `GET /custom-fields?entity_type=lead` returns the seeded fields, etc.

## Files to touch
- `api/src/app/packs/furniture/pack.yaml` (created)
- (no code changes if 4.1 is correct; only the manifest content + a run command)

## Plan
1. Write the YAML.
2. Run installer; capture the output and log via audit.
3. Update `organizations.pack_id`+`pack_version` for demo org.
4. Spot-check via curl that all sections populated.

## Tests to add
- `tests/test_furniture_pack_install.py` — installs to a fresh test org, asserts counts (5 lead stages, 6 custom-order stages, 7 roles, 7 sources, 6 outcomes).

## Verification checklist
**Backend:**
- run: `python -m src.app.scripts.install_pack --org demo --pack furniture --version 1.0.0`
- run: `psql -c "SELECT key, name FROM pipeline_stages WHERE pipeline_id IN (SELECT id FROM pipelines WHERE key='leads' AND org_id=...) ORDER BY display_order;"` → 5 rows in correct order.
- frontend: visit `/leads` → stages match the screenshot.

## Self-check (10 rules)
- [ ] Rule 7 honored: defaults sourced from manifest, not hardcoded in core.
- [ ] Re-running installer is a no-op.

## Stop & report
Await "proceed" before Step 4.3.

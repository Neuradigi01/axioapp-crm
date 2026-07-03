# Step 1 — Real Estate pack manifest + activate onboarding tile

**Goal:** Create `api/src/app/packs/real_estate/pack.yaml` with the full pack contract (pipelines, roles, custom fields, defaults, lead sources, call outcomes, module_permissions) and scaffold the `packs/real_estate/` package layout. The onboarding catalog auto-flips the Real Estate tile from `coming_soon` → `available` because [core/packs/service.py:34-55](../../API/src/app/core/packs/service.py#L34-L55) scans `packs/*/pack.yaml` at startup — no edit to `catalog_config.py` needed.

**Track:** Real Estate CRM Pack
**Status:** COMPLETED
**Depends on:** `phase-4-furniture-pack/` pack.yaml schema (installed and proven) — Done. `onboarding-setup/` catalog endpoint — Done.

---

## Scope

**IN:**

1. Create the pack folder skeleton:
   ```
   api/src/app/packs/real_estate/
   ├── __init__.py
   ├── pack.yaml
   └── modules/
       └── __init__.py
   ```
2. Write [pack.yaml](../../API/src/app/packs/real_estate/pack.yaml) with:
   - `template_id: real_estate`, `version: 1.0.0`, `display_name: Real Estate Retail Pack`
   - **Pipelines** — one board:
     - `listings` (kanban for property listings): `draft → active → under_negotiation → sold → withdrawn`
     - (Site-visit and channel-partner pipelines deferred to Real Estate Phase 2.)
   - **Custom fields** — pack-level fields on `contact` (budget range, preferred locality, property-type interest, purchase intent) and `lead` (budget range, timeline, financing preference, property-type interest).
   - **Roles** — 5 curated roles:
     - `owner` — full `<all>` permission set (same shape as Furniture Owner).
     - `broker` — property management, deal closing, permissions on Property + Contacts + Leads + Pipelines + Conversations + Calls + Billing.
     - `agent` — day-to-day sales, permissions on Property (read/write), Contacts (r/w), Leads (r/w), Appointments (r/w), Walk-ins (r/w), Conversations, Calls.
     - `coordinator` — admin / customer-service, permissions on Contacts (r/w), Appointments, Tasks, Conversations (r/w).
     - `manager` — mid-level oversight, permissions on Property (`*`), Contacts (`*`), Leads (`*`), Pipelines (r/w), Reporting (read), Campaigns (r/w).
   - **Lead sources** — `whatsapp`, `instagram`, `facebook`, `website`, `walk-in`, `reference`, `99acres`, `magicbricks`, `commonfloor`, `broker_network`.
   - **Call outcomes** — `site_visit_booked`, `budget_qualified`, `document_requested`, `financing_discussion`, `callback_requested`, `not_interested`, `wrong_number`.
   - **Defaults** — `currency: INR`, `tax_rate: 5.00` (property registration standard rate), `timezone: Asia/Kolkata`, `locale: en-IN`, `review_source: google`, AI personality + welcome message tailored to real estate.
   - **Follow-up schedule** — day 1 / day 3 / day 7 WhatsApp templates for a fresh property enquiry.
   - **module_permissions** — add `property: [property.read, property.write, property.publish, property.archive, property.delete]` to the existing map. Include the standard Core CRM module_permissions block (contacts, activities, tasks, pipelines, leads, appointments, walk_ins, catalog, staff, conversations, calls, reviews, campaigns, settings, billing) — the pack manifest declares the permission surface it grants.
3. **No `catalog_config.py` edit needed.** [service.get_catalog()](../../API/src/app/core/packs/service.py) already discovers on-disk packs and flips their tile status. The tile's static metadata (name, description, icon, `default_currency`, `default_tax_rate`, `modules_preview`, `display_order`) lives in [catalog_config.py:71-84](../../API/src/app/core/packs/catalog_config.py#L71-L84) and stays unchanged for Step 1.
4. Update [tests/test_packs_catalog.py](../../API/tests/test_packs_catalog.py) — remove `real_estate` from the `coming_soon` assertion list, add it to the `available` assertion. The pre-existing test asserted the old behavior; it would fail otherwise.
5. Add [tests/test_real_estate_pack_manifest.py](../../API/tests/test_real_estate_pack_manifest.py) verifying manifest parses, declares `property.*` permissions, has a `won` stage on the leads pipeline, seeds the 5 curated roles, and the catalog reports `status="available"`.

**OUT:**

- No module code (Property, Site Visit, etc.) — that starts at Step 2.
- No frontend changes — the onboarding tile grid re-renders because the API response changed; no UI code touches this step.
- No Alembic migration — pack manifest doesn't create tables.
- No installer changes — the existing `installer.install(org_id, "real_estate")` will just work once the manifest exists.

## Files touched

| File | Change |
|---|---|
| `api/src/app/packs/real_estate/__init__.py` | New (empty). |
| `api/src/app/packs/real_estate/modules/__init__.py` | New (empty). |
| `api/src/app/packs/real_estate/pack.yaml` | New (~225 lines). |
| `api/tests/test_real_estate_pack_manifest.py` | New (~90 lines): parses manifest, asserts property permission surface, leads pipeline shape, roles, catalog `available`. |
| `api/tests/test_packs_catalog.py` | Modified — real_estate moved from `coming_soon` list to `available` assertions. |

**5 files touched, ~315 lines net new.** Well within Rule 8.

## Verification checklist

- [ ] `uv run python -c "from src.app.packs.installer import parse_pack_yaml; print(parse_pack_yaml('real_estate'))"` — prints the parsed manifest without errors.
- [ ] `GET /api/v1/packs/catalog` — Real Estate CRM appears with `status: "available"`, `default_currency: "INR"`, `default_tax_rate: 5.0`, `modules_preview` from the yaml.
- [ ] Onboarding page `/onboarding` — Real Estate tile is not disabled and can be selected.
- [ ] Submitting `pack_id: "real_estate"` to `/api/v1/auth/onboarding/complete` succeeds (installer runs against the new manifest, org is created, all pipelines/roles/custom fields seed cleanly).
- [ ] Furniture pack still works unchanged (regression check).
- [ ] `uv run pytest tests/packs/test_real_estate_manifest.py -v` — green.

## Self-check against the 10 rules

- **Rule 1** — `core/` doesn't reference the pack. The catalog config only holds placeholder metadata; we remove Real Estate from it because the pack now self-registers.
- **Rule 2** — No new tables in this step.
- **Rule 5** — Sidebar registry untouched; will react in Step 3 when the Property module registers.
- **Rule 6** — Permissions declared in `module_permissions` block; the RBAC composer picks them up during install.
- **Rule 7** — `pack.yaml` is authoritative for every default (pipelines, roles, custom fields, currency, follow-ups). No hardcoded real-estate values anywhere else.

## Raw SQL to paste after install (report only)

Step 1 doesn't run any SQL directly — the installer does that when the first user picks Real Estate at onboarding. Report will include the Alembic-recorded row count from the installer log (pipelines created, roles created, custom_fields created, org_settings updated).

## Stop and report

Report template (per rule 9):

- **Files changed:** list of 5 files above with 1-line summaries.
- **What you can verify:** links to the manifest, the diff in `catalog_config.py`, screenshot / curl output of `/api/v1/packs/catalog` showing `status: "available"`.
- **Tests added:** `tests/packs/test_real_estate_manifest.py` — 3 assertions.
- **Self-check:** 10-rule pass / N/A block per CLAUDE.md.
- **Awaiting your 'proceed'** — Step 2 starts backend models for the Property module.

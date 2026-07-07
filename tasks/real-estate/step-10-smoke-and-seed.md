# Step 10 — Real Estate pack smoke test + demo seed

**Goal:** Install the Real Estate pack into a demo org, seed 5 sample properties (2 draft, 3 published, one with a full image gallery), run the end-to 




-end smoke test covering signup → onboarding pick → sidebar → CRUD → publish → public URL → public page → tamper-detect.

**Track:** Real Estate CRM Pack
**Status:** COMPLETED
**Depends on:** Steps 1–9.

---

## Scope

**IN:**

1. `packs/real_estate/seed_demo.py` — script that:
   - Takes `--org <slug>` arg.
   - Reads sample property data from a bundled `sample_properties.json` (in the same folder).
   - Reads sample images from `packs/real_estate/sample_images/` (5–6 royalty-free stock images bundled — small, ~200 KB each).
   - For each sample property:
     - Insert into `tbl_rp_properties`.
     - Copy image to storage.
     - Insert `tbl_rp_property_images` rows.
     - Set first image as featured.
     - Publish 3 of the 5; leave 2 as draft.
   - Idempotent: skip if slug already exists.

2. `sample_properties.json` — 5 entries covering variety:
   - Villa in Bangalore, 4 BHK, ₹4.5 Cr, published.
   - Apartment in Pune, 2 BHK, ₹85 L, published.
   - Commercial shop in Mumbai, 1200 sqft, ₹2.2 Cr, published.
   - Plot in Coimbatore, 2400 sqft, ₹40 L, draft.
   - Farmhouse near Nashik, 5 acres, ₹1.8 Cr, draft.

3. Sample images — 5 stock JPEGs (600×400 each). Source: bundled with the repo or generated placeholders. Confirm licensing at step start; safest is single-color 600×400 JPEGs with an SVG-rendered watermark ("Sample Property 1", ...) to avoid any third-party licensing question.

4. **End-to-end smoke script** — a manual checklist (also documented at the end of the step report) that walks through:
   1. Create a new user via `/accounts/register`.
   2. On `/onboarding`, pick "Real Estate CRM".
   3. Confirm landing on `/user/dashboard` with Core CRM sidebar + Properties module.
   4. Click Properties → empty state.
   5. Run seed script against this org.
   6. Refresh Properties list → 5 rows visible, tab counts match.
   7. Click "New Property" → create a 6th property manually → save as draft.
   8. Upload 2 images to the 6th property → gallery renders.
   9. Publish the 6th property.
   10. Click "Copy Public URL" → paste in incognito browser → detail loads.
   11. Visit `/properties?org=<slug>` in incognito → grid shows 4 published (3 seeded + 1 manual).
   12. Unpublish one → gone from public grid, still in owner list.
   13. Delete one → gone from both.
   14. Log in as a role without `property.write` → Properties still in sidebar (has `property.read`), but Edit/Create buttons hidden/disabled.

5. Update `tasks/README.md` — flip Real Estate track status from Pending → Completed for closed steps. Add a summary row.

6. **Regression check**:
   - Furniture pack still installs and works.
   - Onboarding for Core CRM still works.
   - No Real-Estate-specific code leaks into `core/` files (grep `real_estate` in `api/src/app/core/` should return 0 hits — only in `catalog_config.py` if any placeholder metadata remains for other verticals).

7. **DB smoke inspection**:
   ```sql
   SELECT id, title, status, published_at FROM tbl_rp_properties WHERE org_id = '<demo_org>';
   SELECT property_id, is_featured, display_order FROM tbl_rp_property_images WHERE property_id = '<sample_property_uuid>' ORDER BY display_order;
   ```

**OUT:**

- Load/performance testing under high image volume — not in v1 scope.
- Cypress/Playwright automation — Rule 8's manual verification cadence is the discipline for this track. Automation can come in a follow-up hardening step.

## Files touched

| File | Change |
|---|---|
| `api/src/app/packs/real_estate/seed_demo.py` | New (~180 lines). |
| `api/src/app/packs/real_estate/sample_properties.json` | New. |
| `api/src/app/packs/real_estate/sample_images/*.jpg` | New (5 files, ~200 KB each). |
| `tasks/README.md` | Modify — mark Real Estate track steps Completed. |
| `tasks/real-estate/README.md` | Modify — flip each step's Status column to Completed. |

**~8 files (+ 5 images).** Within Rule 8.

## Verification checklist

- [ ] Run `uv run python -m src.app.packs.real_estate.seed_demo --org <slug>` — 5 properties + 15+ images installed idempotently.
- [ ] Full manual smoke walkthrough passes (14 checkpoints above).
- [ ] Furniture regression: install a fresh Furniture org, verify sidebar / modules unchanged.
- [ ] SQL smoke query returns expected row counts.
- [ ] `uv run pytest tests/packs/real_estate/ -v` — all module tests still green.
- [ ] Test the token URL from a different browser / incognito to confirm no cookie leakage.
- [ ] Deployment note: `PROPERTY_LINK_ENCRYPTION_KEY` documented in production runbook (Step 5 introduces the env var; Step 10 confirms it's in the ops docs).

## Raw SQL to paste after install (report)

```sql
-- Verify Real Estate seed
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE status = 'published') AS published,
       COUNT(*) FILTER (WHERE status = 'draft') AS drafts
FROM tbl_rp_properties
WHERE org_id = '<demo_org_uuid>';
-- Expected: total=5, published=3, drafts=2 (before manual step 7-9)

-- Verify featured image uniqueness
SELECT property_id, COUNT(*) FILTER (WHERE is_featured = true) AS featured_count
FROM tbl_rp_property_images
GROUP BY property_id
HAVING COUNT(*) FILTER (WHERE is_featured = true) > 1;
-- Expected: empty result (partial unique index enforces one featured per property)
```

## Self-check against the 10 rules

- **Rule 8** — Track closes cleanly, all 10 steps individually verifiable.
- **Rule 9** — Every prior step honored stop-and-report; this closer summarizes.
- **Rule 10** — No TODOs left in the pack or module code.

## Stop and report

- **Files changed:** 8 files + 5 sample images.
- **What you can verify:** the 14-checkpoint smoke walkthrough, SQL row counts, regression check on Furniture.
- **Tests added:** none new — this step is verification of prior steps.
- **Self-check:** full 10-rule audit of the pack directory.
- **Track complete.** Real Estate CRM is live and self-serviceable. Awaiting direction on next track (Real Estate Phase 2 — Site Visits + Channel Partners + Brokerage — or a different priority).

# Step 12 — Frontend: Pipeline Stage dropdown in the mapping editor

**Goal:** Give Owners a UI to set the per-form `pipeline_stage` override that Step 10's schema + Step 11's worker parity already support. Extends the existing field-mapping-editor modal (used by both Google and Meta cards) with a single dropdown at the top; save persists via the existing PATCH endpoint.
**Track:** Ad Integrations
**Status:** COMPLETED
**Depends on:** Step 10 (backend schema + PATCH endpoint accept `pipeline_stage`), Step 11 (both workers consume it), Step 9 (Meta card exposes the "Edit Mapping" button).

---

## Scope

In-scope:

- **`integrations-api.service.ts`** — extend the wire shapes so the field lands in every request/response:
  - `IntegrationSubscription.pipeline_stage: string | null`
  - `SubscriptionCreatePayload.pipeline_stage?: string | null`
  - `SubscriptionUpdatePayload.pipeline_stage?: string | null`

- **`field-mapping-editor.component.ts`** — extend the modal:
  - Inject `PipelinesApiService`.
  - Load the org's `leads` pipeline on first open, in parallel with the mapping targets fetch (`forkJoin`).
  - New `pipelineStage` signal seeded from `subscription.pipeline_stage` (or empty = "default").
  - `save()` calls `updateSubscription(id, { pipeline_stage })` first (validated), then `updateSubscriptionMapping(id, mapping)` — sequenced so the field is legal before the mapping lands. Failure on either surfaces inline.

- **`field-mapping-editor.component.html`** — dropdown at the top of the body:
  - Label: "Pipeline stage for new leads"
  - First option: "(Org default — first stage)" (empty value)
  - Followed by every stage from the loaded leads pipeline in `display_order`.

Out of scope:

- Owner-assignment override UI (future).
- Per-Meta-form pipeline picker on the card outside the modal (avoids UI duplication).

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/settings/integrations/integrations-api.service.ts` | modified — 3 type extensions |
| `app/src/app/features/user/core/settings/integrations/field-mapping-editor.component.ts` | modified — load stages, pipelineStage signal, sequenced save |
| `app/src/app/features/user/core/settings/integrations/field-mapping-editor.component.html` | modified — dropdown block above the mapping table |

Three files, zero new components, no new backend surface.

## Verification

1. Open the mapping editor on a Google-Ads or Meta subscription → dropdown shows every stage of the org's leads pipeline plus the default option.
2. Pick "qualified" → Save → PATCH request body contains `{"pipeline_stage":"qualified"}` and the following PUT `/mapping` request lands the field mapping; both return 200.
3. Reload the modal → dropdown pre-selects "qualified".
4. Send an ad lead through the webhook → resulting lead lands in "qualified".
5. Reset the dropdown to default → Save → PATCH clears the override; subsequent leads land in the org's default first stage.

## Self-check

- ✅ 10 rules: no `/core → /packs` boundary crossed; existing forms-render-dynamically model preserved; ≤10 files; no TODOs.
- ✅ Reuse: existing `PipelinesApiService.getByKey('leads')`, existing `updateSubscription` PATCH client, existing `updateSubscriptionMapping` PUT client. No new API surface.
- ✅ Prettier + lucide-icon registry: no new icons added; palette/spacing match the existing modal.

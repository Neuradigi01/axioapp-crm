# Phase 6 — Furniture Pack Features (Layer 2)

**Goal:** Build out the furniture-vertical features that demonstrate the pack architecture — marketplace integrations (Amazon / Flipkart / Shopify), In-Store QR marketing, and AI Virtual Staging.

**Phase completion criteria:** Multi-channel commerce works (orders flow in from marketplaces). QR campaign codes generate + track scans. AI Virtual Staging produces preview images. All wired through the `packs/furniture/` Layer-2 namespace — `core/` knows nothing about any of it.

**This phase is post-launch.** It is **not** part of shipping the generic core CRM template. Skip entirely if your near-term goal is "ship a generic CRM template + onboard a non-furniture pilot." Come back to these once the template has paying customers and the furniture vertical is the next bet.

---

## Steps

| # | Title | Status |
|---|---|--------|
| 6.1 | [Marketplace abstraction](step-6.1-marketplace-abstraction.md) | Pending |
| 6.2 | [Amazon adapter](step-6.2-marketplace-amazon.md) | Pending |
| 6.3 | [Flipkart adapter](step-6.3-marketplace-flipkart.md) | Pending |
| 6.4 | [Shopify adapter](step-6.4-marketplace-shopify.md) | Pending |
| 6.5 | [Marketplace frontend](step-6.5-marketplace-frontend.md) | Pending |
| 6.6 | [In-Store QR Marketing](step-6.6-qr-marketing.md) | Pending |
| 6.7 | [AI Virtual Staging: backend](step-6.7-virtual-staging-backend.md) | Pending |
| 6.8 | [AI Virtual Staging: frontend](step-6.8-virtual-staging-frontend.md) | Pending |

## Dependencies

- All steps depend on Phase 4 (Furniture Pack & First Modules) complete.
- 6.2 / 6.3 / 6.4 (marketplace adapters) depend on 6.1 (abstraction).
- 6.5 (marketplace frontend) depends on 6.1–6.4.
- 6.8 (virtual staging frontend) depends on 6.7.
- Most steps also benefit from Phase 5 — Core CRM v1 Launch being shipped first (real customers > speculative features).

## Why this is "later, not now"

Every step in this phase is **Layer 2 — furniture pack only**. A salon adopting the CRM template doesn't need marketplace adapters. A real-estate firm doesn't need virtual staging. None of this work generalises — it's specific to the furniture vertical, useful for the furniture showcase, irrelevant for adopters of the template at large.

If a furniture pilot customer signs up post-launch, this phase is the roadmap that turns the demo `demo` org into a real furniture-business deployment. Until that happens, focus on [Phase 5 — Core CRM v1 Launch](../phase-5-core-crm-launch/README.md).

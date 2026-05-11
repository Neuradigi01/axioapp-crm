# Step 6.8 — Documentation

**Goal:** README, architecture docs (with the Layer 1 / Layer 2 diagram), API reference (OpenAPI auto-generated), contributor guide for adding a new pack module.
**Phase:** 6
**Depends on:** all prior
**Status:** Pending

## Scope
**In-scope:**
- Top-level `README.md` — what the product is, how to run, where to find docs.
- `docs/architecture.md` — layered architecture, registries (modules, permissions, channels, marketplaces), pack manifest, multi-tenancy.
- `docs/api.md` — points at `/docs` (FastAPI auto-OpenAPI) and lists key endpoints.
- `docs/adding-a-pack.md` — step-by-step guide: define manifest, add modules under `app/packs/<id>/modules/...`, register descriptors, install via CLI.
- `docs/data-model.md` — list of tables with brief description; ERD link.
- `CLAUDE.md` — already present from 1.1; ensure up to date.
- README diagrams — use Mermaid for layer split.

## Files to touch
- `README.md` (replaced)
- `docs/architecture.md` (created)
- `docs/api.md` (created)
- `docs/adding-a-pack.md` (created)
- `docs/data-model.md` (created)
- `docs/screenshots/*.png` (created — captured from running app)

## Plan
1. Write the docs from the actual codebase state (don't speculate).
2. Mermaid diagrams.
3. Verify links + code refs render.

## Tests to add
- N/A — docs only. Add a `mkdocs build` lint if we adopt mkdocs (optional).

## Verification checklist
**Docs:**
- README renders in GitHub preview.
- All links resolve.

## Self-check (10 rules)
- [ ] Diagrams accurately reflect the code.

## Stop & report
Await "proceed" before Step 6.9.

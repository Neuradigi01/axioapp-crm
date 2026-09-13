# Archived documents

Superseded planning and reference documents, kept for build history rather than
guidance. **Nothing here describes how the system works today** — check the code,
`CLAUDE.md`, or the relevant `tasks/` track before trusting anything in this folder.

| Document | What it was | Why it is archived |
|---|---|---|
| [`PAGE-TO-TABLE-MAP.md`](PAGE-TO-TABLE-MAP.md) | Generated map of every UI page to the DB tables it reads/writes | A point-in-time snapshot from 2026-06-01. Many modules have shipped since; regenerate rather than trust it. |
| [`WHATSAPP_CAMPAIGNS_PLAN.md`](WHATSAPP_CAMPAIGNS_PLAN.md) | Scoping doc for the bulk-WhatsApp campaign engine | Planning doc, explicitly never a replacement for the `tasks/` step files. The work shipped via `tasks/phase-3.5-whatsapp-campaigns/` and `tasks/whatsapp-platform-upgrade/`. |
| [`catalog-image-upload-plan.md`](catalog-image-upload-plan.md) | Implementation plan for catalog product image upload | Marked "implementation pending" in 2026-06; the feature has since shipped. |

Live operational guides stay one level up in [`docs/`](../).

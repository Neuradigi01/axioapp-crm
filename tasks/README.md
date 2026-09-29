# Core CRM — Task Tracks

This folder holds the **in-flight build tracks**. One folder per track: a `README.md`
carrying the plan, and one `step-*.md` per individually verifiable step.

Before writing a new track plan or any step files, read [`PLANNING_RULES.md`](../PLANNING_RULES.md).
The rules every step is judged against live in [`CLAUDE.md`](../CLAUDE.md).

## History — read this before looking for a step file that isn't here

The original **76-step plan** (`phase-1-foundation/` … `phase-6-furniture-pack-features/`)
and ~44 completed side tracks were removed on 2026-09-13 once their work had shipped.
Core CRM is built: every Layer 1 module exists under `API/src/app/core/`, the staff
portal is live, and the furniture pack has real modules under `API/src/app/packs/furniture/`.

Those step files described work that is now **code**, and their status tables had drifted
badly enough to be misleading — most shipped work was still labelled "Pending". The code,
its tests, and `git log` are the accurate record now.

To read a deleted track:

```bash
git log --oneline --diff-filter=D -- 'tasks/phase-2-core-crm/*'   # find the removing commit
git show <commit>^:tasks/phase-2-core-crm/README.md               # read a file from before it
```

One artefact was kept rather than deleted because `CLAUDE.md` rule 2 cites it as
normative: the `tbl_` naming map, now at [`API/docs/TABLE_NAMING_MAP.md`](../API/docs/TABLE_NAMING_MAP.md).

## Active tracks

| Track | Steps | Last touched | What it is |
|---|---|---|---|
| [r2-storage](r2-storage/README.md) | 10 | 2026-09-29 | Move uploaded files from `./storage` to Cloudflare R2 (private bucket per env, API-streamed `/files`) |
| [custom-events](custom-events/README.md) | 18 | 2026-09-11 | User-defined event triggers for workflows and templates; public `POST /events/track` folded into `core/public_ingest/` |
| [variables-unification](variables-unification/README.md) | 13 | 2026-09-11 | One variable registry behind every template / workflow / chatbot / automation-condition picker |
| [mailgun-inbound](mailgun-inbound/README.md) | 9 | 2026-09-10 | Reply-capture for SMTP senders via Mailgun inbound routing |
| [ad-integrations](ad-integrations/README.md) | 13 | 2026-09-07 | Google Ads + Meta Ads lead ingestion |
| [ai-assistants](ai-assistants/README.md) | 17 | 2026-08-19 | Org-scoped BYOK chat assistants |
| [leads-update-status-flow](leads-update-status-flow/README.md) | 5 | 2026-08-17 | Lead status transition flow |
| [workflow-scheduling](workflow-scheduling/README.md) | 7 | 2026-08-06 | Scheduled / time-based workflow runs |
| [design-refresh](design-refresh/README.md) | 22 | 2026-07-27 | Adopt the AIXO visual system across every page; no business-logic changes |

**Step statuses inside these track READMEs are not maintained and should not be trusted.**
Check the code before assuming a step is outstanding.

## Reference

[`CICD_BOOTSTRAP_PROMPT.md`](CICD_BOOTSTRAP_PROMPT.md) — the deployment design decisions
and failure modes carried over from a sibling project. It is the spec for the
environment-separation and CI/CD work, not a track of its own.

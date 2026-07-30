# Planning Rules — the design-time gate

**Read this before writing a track plan or any step files.** It is the gate between "we decided to build X" and "here are the step files." It costs ~20 minutes and exists to stop the cycle where an audit finds, after implementation, something one question at design time would have caught.

**Applies to:** any new track under `tasks/<track-name>/`, and any material reshape of an existing one. The **plan document** is `tasks/<track-name>/README.md`; **step files** are `tasks/<track-name>/step-*.md`.
**Not this file's job:** reviewing code that already exists — that is [`REVIEW_CHECKLIST.md`](REVIEW_CHECKLIST.md).

---

## Part A — before any step file exists

Run all six on the plan document. Do not skip ahead to writing steps.

### 1. Judge the shape first

**Do not assume the requested shape is correct — question it.** What should this feature have to be *complete*? What is **missing**? What is **redundant** — two things that are really one? What sits in the **wrong place**?

### 2. Benchmark against the incumbents

For anything mature competitors already do, state **how they do it and why we differ.** A deliberate difference is fine and worth recording; an accidental one is an undiscovered bug. **This single check catches the largest class of miss.**

**Benchmark against `PRODUCT_BRIEF.md` — the researched, sourced brief — not against memory.** If the brief does not cover this area, run a **scoped teardown of just that area** per [`DISCOVERY_RULES.md`](DISCOVERY_RULES.md) (two hours, stage 2 only) before planning. Do not fall back to recall: a remembered competitor fact is compressed, dated, and indistinguishable in the output from a sourced one. Where the brief is silent and a teardown is genuinely out of scope, **say so in the plan** rather than asserting an unsourced claim.

*Until a brief exists*, the interim benchmarks are **HubSpot · Zoho CRM · Pipedrive**, plus the per-area table in [`REVIEW_CHECKLIST.md` §3.1](REVIEW_CHECKLIST.md) — inbox → Intercom/Wati/Interakt/Respond.io; automation → HubSpot Workflows/ActiveCampaign/Zapier; campaigns → Mailchimp/Klaviyo; billing → Stripe Billing/Chargebee. Any claim drawn from these carries no source, so mark it **unsourced** in the plan.

### 3. Four lenses, run on the plan

**Security & abuse — think like an attacker, not a careless user.**

- **Tenant isolation.** Can org A reach, block, or affect org B? Is `org_id` taken from the JWT / `TenantContextMiddleware`, never from a client-supplied field? Does every new table carry `org_id` + RLS?
- **Privilege escalation.** Does a **server-side** permission check exist, or only the frontend guard?
- **Mass assignment.** Can a request write a field it does not own — `role`, `org_id`, `owner_id`, `is_active`, balance/credits, subscription tier?
- **Webhook / callback forgery.** Meta, WhatsApp Cloud API, Stripe, Google/Microsoft OAuth. Is the signature verified **before any side effect**, compared **constant-time**, and are **replays rejected** (timestamp window + seen-id)?
- **File upload.** Path traversal under `./storage/{org_id}/{entity}/{file_id}`, content-type spoofing, archive/CSV bombs — and is the file served from a route that skips auth?
- **Token / session.** Replay, fixation, refresh reuse — and **what is claimable**: can a second user claim a token, device, phone number, or slug the first already holds?
- **Injection of every kind**, including **SSRF** on any URL the *server* fetches (webhook targets, image fetches, OAuth redirects).
- **What is unbounded?** Especially on public or unauthenticated endpoints.

**Performance at scale.** What grows without a cap? What will be N+1? What index does the implied query need (usually an `org_id` composite)? What belongs in Celery rather than the request?

**Code organisation.** Where does each piece land under Router → Service → DAL, and `core/` vs `packs/`? **Does something here already exist that should be *extended* rather than created?**

**Design fit.** Is this the right *model*, or should it be reworked? This questions the design, not the code inside it.

### 4. Hunt for what the plan does NOT say

**Highest-value item on this page — run it as its own deliberate pass.** Reviewers naturally check what *is* written; finding absence is a different mental mode and does not happen by accident.

- **Which case did we picture only one user doing?** Write the two-user version: **"A does X, then B does X — then what?"**
- **What starts and never finishes?** Who cleans it up?
- **What gets created but never deleted, expired, or re-claimed?** Including: what happens to this record when its **parent is merged or deleted**?
- **What is *asserted* by the caller that the code treats as *proven*?**

### 5. Check the order

Does any step need something a later step builds?

### 6. Three required sections in the plan document

| Section | Contents |
|---|---|
| **Decisions** | What we chose and **why** — including the §2 competitor comparison and every deliberate difference. Any decision resting on a competitor or platform claim **cites the `PRODUCT_BRIEF.md` section or a URL**; if neither exists, it is marked unsourced. (`tasks/workflows/README.md` names this *"Locked design choices (won't relitigate during implementation)"* — that heading is equally valid.) |
| **Cases** | The answers from §4, one line each. |
| **Tests** | What will prove each step works, named **before** the code exists. Name the assertion, not a count: *"merging a contact that has consent events preserves both histories"* — not *"12 pytest"*. |

---

## Part B — per step file (deliberately light)

A step lives inside an already-approved shape. **Do not re-run Part A on it** — that burns enormous time for almost nothing. Three questions:

1. Does this contradict a recorded **Decision**, or another step?
2. Are the **files and layers** it names correct per CLAUDE.md's Router → Service → DAL and `tbl_` rules?
3. What **test** proves it works?

---

## Part C — the gate

When the plan is written, **you spawn three reviewers in parallel** before showing anything to the user. The user does not run a separate session.

Three rules make this work, and it fails without them:

1. **Hand each reviewer the plan document and nothing else.** Not your reasoning, not your justification. Independence comes from *what a reviewer is given*, not from who spawned it — a reviewer shown the argument for a plan will agree with it.
2. **The briefs below are fixed text — paste them verbatim.** Do not compose a friendlier version. An agent asked to commission criticism of its own work softens the ask unprompted.
3. **Nothing is auto-applied.**

### The briefs

Prefix each with: *"Read `tasks/<track>/README.md`. That document is your only input. **Do not run any git command.** Report findings most-severe-first; if your lens turns up nothing, say so plainly."*

> **Attacker.** You are a hostile security reviewer. This is a multi-tenant SaaS CRM: every org's data sits in shared tables separated only by `org_id`, RLS policies, and per-query scoping. Find what an attacker could actually *do* under this plan. Walk: tenant isolation and IDOR; privilege escalation and missing server-side permission checks; mass assignment (`role`, `org_id`, `owner_id`, balances, tier); webhook/callback forgery across Meta, WhatsApp Cloud API, Stripe and OAuth — is the signature verified before any side effect, constant-time, and are replays rejected; file-upload attacks against local-disk storage; token/session replay, fixation, refresh reuse, and what is *claimable* by a second user; injection of every kind including SSRF on any URL the server fetches; what is unbounded or unauthenticated. For each finding give a concrete exploit scenario, a severity, and a fix.

> **Architect.** Judge this plan's shape, not its wording. (a) What should this feature have to be complete — what is missing, what is redundant (two things that are really one), what sits in the wrong place? Do not assume the requested shape is correct. (b) Benchmark it against HubSpot, Zoho CRM and Pipedrive, plus the per-area benchmarks in `REVIEW_CHECKLIST.md` §3.1: for anything they already do, state how they do it and whether our difference is deliberate or accidental. (c) Design fit — is this the right model, or should it be reworked? (d) Code organisation — does each piece land correctly under Router → Service → DAL and `core/` vs `packs/` per CLAUDE.md, and does something already exist that should be extended rather than created?

> **Absence.** Your only job is to find what this plan does **not** say. Do not review what is written — the other reviewers do that. For each capability in the plan, answer: (1) Which case was pictured with only one user? Write the two-user version — "A does X, then B does X, then what?" (2) What starts and never finishes, and who cleans it up? (3) What gets created but never deleted, expired, or re-claimed — including what happens to a record when its parent is merged or deleted? (4) What does the caller assert that the code treats as proven? A plan that answers none of these has not been reviewed for absence; say so plainly.

### After the reviewers return

Consolidate **most-severe-first**. State where you **disagree** with a reviewer and why. Present to the user. **Revise only what they accept** — then write the step files.

# Discovery Rules — research before building something new

The standing rule for researching a category **before** it gets planned or built. It produces `PRODUCT_BRIEF.md`, which every later plan is then checked against.

Related: [`PLANNING_RULES.md`](PLANNING_RULES.md) gates a *plan* once the brief exists. [`REVIEW_CHECKLIST.md`](REVIEW_CHECKLIST.md) reviews *code* once it exists. This file comes before both.

---

## Rule zero — never answer from memory

**Every factual claim in a discovery pass — about a competitor, a platform, a provider, or a regulation — must cite a URL actually fetched in this session.** Not recalled. Fetched.

**Why this is rule zero:** a model's recollection of a product is compressed, dated and generic. It reliably produces the *shape* of a right answer — a pricing tier that sounds plausible, a feature list that reads like the category — with the specifics wrong or two years stale. And it fails **silently and confidently**: nothing in the output distinguishes a fetched fact from a remembered one. **Answering from memory is the failure this file exists to prevent.**

This is not hypothetical here. Today this repo carries 38 mentions of HubSpot, 38 of Zoho, 23 of Salesforce across its `tasks/` tree and the benchmark table in [`REVIEW_CHECKLIST.md` §3.1](REVIEW_CHECKLIST.md) — and **not one URL**. Those claims have been steering real design decisions on recall alone.

**If web access is unavailable, STOP and say so.** Do not proceed on recall and disclaim it afterwards.

---

## When to run this — and when not to

**Run discovery for:**

- A new product, or a new vertical pack.
- **A surface this project has never built.** This is the common trigger here — the product is mature, so the realistic cases are a first telephony provider, a new payment region, a new channel (Instagram DM, RCS), a BI/analytics surface, a marketplace.
- An expensive-to-reverse decision the brief doesn't cover — an entity model, a provider commitment, a pricing model, a data-residency choice.
- A brief older than **~6 months** when planning something major.

**Do NOT run discovery for:** a field, a page, a filter, a report, a setting, or ordinary feature work. Those benchmark against the existing brief.

**Running discovery per-feature is its own expensive failure.** It converts a two-hour task into a two-day one and trains everybody to skip the gate when it actually matters.

**Timebox it.** A full pass is **one working day**; a scoped single-area teardown is **two hours**. Research is a comfortable way to avoid building — when the box is spent, write the brief with what you have and mark the gaps as open questions.

---

## The stages

### 1. Place the category

Before comparing anything, work out what *this* is:

- What is the category called — the term buyers and analysts actually use?
- **Is this a product, or a feature of somebody else's product?** Answer this honestly and early. It is the cheapest possible kill.
- Who buys it, and what do they pay? Per seat, per contact, per message, flat?
- The **4–6 real players**, each with a URL. Real means currently sold, not a dead blog post.
- Is the category **mature, consolidating, or open**?

**Then STOP and show the user the competitor list before going deeper.** They can spot a dead product, a wrong segment, or a missing obvious player in thirty seconds; an agent cannot. Everything downstream inherits this list, so a wrong list wastes the whole pass.

### 2. Teardowns

One pass per competitor, reading **their own material** — not summaries, not comparison-site listicles, not recall:

| Source | What it gives you |
|---|---|
| Product / feature pages | claimed scope |
| Help centre & docs | how it actually behaves |
| **API reference** | **the data model — this is where entities are visible** |
| Pricing page | packaging, limits, what's gated |
| Changelog / release notes | direction, and what they removed |
| G2 · Reddit · community forums | **what users hate** — available nowhere else |

Return for each: **entities and how they're modelled** · features by area · packaging and limits · surprises · complaints · **every URL fetched**.

Then produce a **screenshot shopping list**: 6–10 *named* screens for the user to capture ("HubSpot → workflow enrollment settings", "Wati → template submission form"). An agent cannot log into a competitor's product; the user can, and the inside of the product is where the real model lives.

### 3. Constraint sweep

**The stage that looks skippable and is not.** Competitors tell you *what to build*. **Platforms tell you what you are allowed to build** — and that is the class of fact that forces rewrites, because it is invisible until you ship.

For every third party this product would depend on — payments, email, messaging, telephony, the LLM vendor, cloud region — and every applicable regulation, read **their** documentation and answer:

- What is **globally unique**, and scoped to whom?
- What **requires approval**, and how long does it take?
- What **hard time windows** exist that we don't control?
- What is **rate-limited or quota-capped** — and is that quota **per-customer or shared across all our customers**? (Shared quotas turn one noisy tenant into an outage for everyone.)
- What will be **silently undeliverable** even though our database accepted it?
- What is **prohibited outright** in the target region?

For this project that list currently means at minimum: **Meta lead ads · WhatsApp Cloud API (and the Baileys sidecar) · Stripe · Google and Microsoft OAuth (Gmail, Outlook, Calendar) · Firebase push · the AI provider · local file storage · India DPDP and GDPR.**

Each finding is **one sentence with a source**:

> *"X is impossible / capped / requires approval, because `<provider>` `<rule>` — source: `<URL>`."*

**What this looks like when it goes right and when it goes wrong.** [`WHATSAPP_CAMPAIGNS_PLAN.md:72`](WHATSAPP_CAMPAIGNS_PLAN.md#L72) records that business-initiated WhatsApp messages need pre-approved templates and free-form text only works inside the 24-hour customer-service window — a perfect constraint-sweep finding. It was found **reactively, mid-build**, and it still lives in a plan document rather than as an enforced rule. A message our own database accepts and queues can be permanently undeliverable at Meta. That is the exact shape of the fact this stage exists to find *first*.

### 4. Synthesise

- **Feature matrix** — rows are capabilities, columns are competitors.
- **The entity model** — what the products converged on calling things, and how those things relate. Convergence across three independent products is a hard-won lesson, not a coincidence; when three CRMs all separate "contact" from "lead" from "deal", that boundary was paid for.
- **Where they agree** (table stakes) and **where they differ** (the differentiation space).

**A screen is cheap to change. An entity becomes the database and is not.** Research that comes back with a menu structure and no entity model has skipped the expensive half — and in a multi-tenant schema where every table carries `org_id` and RLS, an entity mistake is a migration across live tenants.

### 5. Absence hunt

- What do they **all** do that we hadn't thought of — and **why** do they all do it?
- What does a buyer expect as **table stakes** that isn't on our list?
- What **operational surface** does every mature product have that a first version forgets — audit trail, exports, roles and permissions, rate limits, retention and deletion, offboarding, seat changes, billing proration?
- What did any of them **build and then visibly remove**? A removed feature is a documented, expensive lesson someone else paid for.

### 6. The wedge

- What we'd do **differently**, and why that is worth a buyer's money rather than just our own preference.
- The explicit **NOT-BUILDING list**. A wedge without one is a wish.
- **Who this is for, narrowly.**
- **Kill criteria** — a **number and a date** whose failure means stop or pivot, not try harder. *A target that can only be passed is not a test.*

These are the user's calls, not the agent's. **Propose and wait.**

### 7. The gate

Spawn **three independent reviewers** and give each **only the finished brief** — not the research notes, not the reasoning, not each other's findings.

The three mechanics that make this work — reviewers get the artifact and nothing else; briefs are pasted verbatim; nothing is auto-applied — are stated once in [`PLANNING_RULES.md` Part C](PLANNING_RULES.md) and apply here unchanged. **Do not compose friendlier briefs:** an agent asked to commission criticism of its own work softens the ask unprompted. Tell every reviewer explicitly: **do not run any git command.**

Use this wording verbatim:

> **INCUMBENT:** What does every product in this category have that this brief does not mention? Where does the brief describe a competitor from a marketing page rather than from their docs, API reference or help centre?

> **CONSTRAINT:** Which platform, provider or legal rule will force a redesign later, and is it in here? Name a dependency whose own rules were never read.

> **SKEPTIC:** Why does this fail? Who already does it better? Is this a product, or a feature of somebody else's product? Is the wedge something a buyer pays for, or a preference we happen to hold?

Consolidate findings **most-severe-first**, state plainly **where you disagree with a reviewer and why**, present to the user, and **apply nothing automatically**.

---

## The output — `PRODUCT_BRIEF.md`

| Section | Contents |
|---|---|
| **Category** | What it's called, and whether this is a product or a feature of somebody else's |
| **Competitors** | The 4–6 players, each with URLs |
| **Feature matrix** | Capabilities × competitors |
| **Entity model** | What they converged on, and how the entities relate |
| **Constraint register** | One sourced sentence per rule |
| **Convergence & divergence** | Table stakes vs differentiation space |
| **The wedge** | Including the NOT-BUILDING list and who it's for |
| **Kill criteria** | A number and a date |
| **Expensive-to-reverse decisions** | Each with its reasoning |
| **Open questions** | What the timebox didn't reach |

**Every factual claim carries its URL. Uncertainty is marked as uncertainty. A thin section says it is thin** — padding a section to look complete is worse than an honest gap, because the gap is what tells the next reader where to look.

---

## What this does not buy

This does not make the vision correct on day one. Some clarity only arrives by building, and no amount of reading substitutes for a real user's first week.

What it removes is **the knowable part**: the category you didn't know existed, the table-stakes feature everyone ships, the entity model several products converged on years ago, and the platform rule that was in public documentation the whole time.

*Illustration from another project — not this repo's history:* roughly three months went into building, then discovering what the category already expected, then rebuilding. Almost all of it was knowable in advance from public documentation. The later rewrites came not from the original idea being wrong, but from **new surfaces months in**, when nobody was thinking about research any more. That is the case this file is built for, and the reason the rule lives in the repo rather than in anyone's memory.

# Branch protection — the merge gate

Quality checks ([`.github/workflows/quality.yml`](.github/workflows/quality.yml)) only
*block merges* if the branch is protected to require them. Protection is a GitHub-side
setting that needs **admin auth**, so it can't be a passive file in the repo — apply it
**once** with the committed script, or click through the UI below.

## Option A — committed script (recommended)

```bash
# Requires the gh CLI, authenticated with admin rights on the repo:
gh auth login
bash .github/setup-branch-protection.sh
```

The script is **idempotent** (create-or-update by ruleset name) — safe to re-run after
editing. It creates a single repository **ruleset** named `Core CRM — protect dev & main`.

## Option B — GitHub UI (click-by-click)

1. Go to **`https://github.com/Neuradigi02/Crm/settings/rules`** → **New branch ruleset**.
2. **Ruleset Name:** `Core CRM — protect dev & main`.
3. **Enforcement status:** **Active**.
4. **Bypass list:** leave **empty** — *do not add anyone, including admins/roles*. (This is
   what makes the checks enforce on everyone.)
5. **Target branches** → **Add target** → **Include by pattern**: add `dev`, then add `main`
   (two patterns, or `Include default branch` + a pattern for `dev`).
6. Under **Rules**, enable:
   - ☑ **Restrict deletions**
   - ☑ **Block force pushes**
   - ☑ **Require a pull request before merging**
     - **Required approvals: `0`** (see note below)
     - leave "Require review from Code Owners" **off** for now
   - ☑ **Require status checks to pass**
     - ☑ **Require branches to be up to date before merging**
     - **Add checks:** search and add **`python`** and **`frontend`**.
       *(These appear only after the `quality` workflow has run at least once — open a
       PR into `dev` first to register them, then add them here.)*
7. **Create**.

## Verifying it works

Open a PR from a feature branch into `dev`. You should see the `python` and `frontend`
checks run, and **Merge** stays disabled until both pass. Force-pushing to `dev`/`main`
and deleting those branches are now blocked.

## Note: checks vs. approvals (important)

These two dials are independent:

- **Status checks** (`python` + `frontend`) enforce **code QUALITY on everyone**, no matter
  who opens or merges the PR. Empty bypass list = no exceptions.
- **Required approvals** is a **separate human-review** dial. It is set to **0** on purpose:
  GitHub forbids approving your own PR, so a solo owner with "require 1 approval" would be
  permanently deadlocked. Quality is still enforced by the checks.

When a **second teammate** joins, raise human review by:

1. Editing [`.github/CODEOWNERS`](.github/CODEOWNERS) with the real handles/teams.
2. Creating a **second ruleset** that adds **Require a pull request → 1 approval +
   Require review from Code Owners**, and lists the owner as a **bypass actor for that
   ruleset only**. Keep *this* (quality) ruleset's bypass list **empty** so the owner's own
   commits still have to pass `python` + `frontend`.

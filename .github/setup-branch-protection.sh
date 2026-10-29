#!/usr/bin/env bash
# Idempotent branch-protection setup for Core CRM, using GitHub Repository
# Rulesets (the modern replacement for "branch protection rules").
#
# Protects `dev` (integration) and `main` (production) with:
#   • Active enforcement
#   • Require a pull request before merging (0 required approvals — see note)
#   • Require status checks `python` + `frontend` to pass
#   • Require branches to be up to date before merging (strict)
#   • Block force pushes (non-fast-forward)
#   • Restrict deletions
#   • Empty bypass list — NO ONE bypasses, including admins
#
# Why 0 required approvals: GitHub forbids approving your own PR, so a solo owner
# with "require 1 approval" would be permanently deadlocked. The status checks
# above still enforce QUALITY on everyone regardless of who merges. "Required
# approvals" is a SEPARATE, human-review dial: when a second teammate exists,
# raise it to 1 (+ Code Owner review) — and put THAT requirement in a SECOND
# ruleset that lists the owner as a bypass actor for approvals only, so this
# ruleset keeps the owner's own commits subject to the checks.
#
# Requires: gh CLI authenticated with admin rights on the repo (`gh auth login`).
# Run:      bash .github/setup-branch-protection.sh
set -euo pipefail

RULESET_NAME="Core CRM — protect dev & main"

command -v gh >/dev/null 2>&1 || { echo "error: gh CLI not found. Install: https://cli.github.com/"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "error: gh not authenticated. Run: gh auth login"; exit 1; }

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
echo "Repository: $REPO"

PAYLOAD=$(cat <<JSON
{
  "name": "$RULESET_NAME",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {
    "ref_name": { "include": ["refs/heads/dev", "refs/heads/main"], "exclude": [] }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "allowed_merge_methods": ["merge", "squash", "rebase"]
      }
    },
    { "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "do_not_enforce_on_create": false,
        "required_status_checks": [
          { "context": "python" },
          { "context": "frontend" }
        ]
      }
    }
  ]
}
JSON
)

# Find an existing ruleset with this name (idempotent create-or-update).
EXISTING_ID=$(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name==\"$RULESET_NAME\") | .id" 2>/dev/null | head -n1 || true)

if [ -n "${EXISTING_ID:-}" ]; then
  echo "Updating existing ruleset #$EXISTING_ID ..."
  printf '%s' "$PAYLOAD" | gh api -X PUT "repos/$REPO/rulesets/$EXISTING_ID" --input - >/dev/null
  echo "✓ Ruleset updated."
else
  echo "Creating ruleset ..."
  printf '%s' "$PAYLOAD" | gh api -X POST "repos/$REPO/rulesets" --input - >/dev/null
  echo "✓ Ruleset created."
fi

echo ""
echo "Done. Verify at: https://github.com/$REPO/settings/rules"
echo "Note: the 'python' and 'frontend' checks become selectable/recognized once"
echo "the quality workflow has run at least once (open a PR into dev to trigger it)."

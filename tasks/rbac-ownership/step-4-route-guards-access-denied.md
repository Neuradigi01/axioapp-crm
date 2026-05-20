# Step 4 — Frontend route guards + Access Denied page

**Goal:** Add a uniform permission-key-driven route-guard layer to the FurnitureCRM frontend, plus a styled `/user/access-denied` page. Direct URL access to forbidden routes is blocked at the router level, not just hidden in the sidebar.
**Track:** RBAC, Ownership & Self-Signup
**Status:** Pending
**Depends on:** 1.6 (JWT + `/users/me` returns the permission key list), Phase 2.5 (admin routes exist as gating targets).

---

## Scope

Two pieces:

1. **`permissionGuard(...keys)`** — Angular `CanActivateFn` that checks `currentUser.permissions` against the required key(s). If missing, redirect to `/user/access-denied`. If unauthenticated, redirect to `/accounts/login?return_url=<original>`.
2. **Access Denied page** at `/user/access-denied` — styled, role-aware ("Your role *{role.name}* does not include access to this page"), with a back-to-dashboard link.

Apply guards to:

| Route | Guard |
|---|---|
| `/user/settings/users` | `permissionGuard('users.read')` |
| `/user/settings/roles` | `permissionGuard('roles.read')` |
| `/user/settings/billing` | `permissionGuard('billing.read')` |
| `/user/reports/...` | `permissionGuard('reports.read')` |
| `/user/leads/:id/edit` | `permissionGuard('leads.write')` |
| `/user/audit-logs` | `permissionGuard('audit.read')` |
| (every other `/user/...` route) | `authGuard` only (just "logged in & in an org") |

Owner-only client-side gating happens via the same mechanism — Owner has all keys (per Step 2's `ALL_KEYS` sentinel), so `permissionGuard('billing.read')` admits Owner naturally.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/shared/guards/permission.guard.ts` | created |
| `app/src/app/features/user/core/shared/guards/auth.guard.ts` | created / modified — if exists, ensure it redirects to `/accounts/login?return_url=` |
| `app/src/app/features/user/core/shared/services/current-user.service.ts` | modified — expose `permissions: Signal<Set<string>>` reading from `/users/me` |
| `app/src/app/features/user/core/access-denied/access-denied.component.{ts,html,scss}` | created |
| `app/src/app/features/user/user.routes.ts` | modified — register `/access-denied` route + apply guards to listed paths |
| `app/src/app/features/user/core/settings/settings.routes.ts` | modified — apply guards to settings sub-routes |
| `app/src/app/features/user/core/leads/leads.routes.ts` | modified — apply guards to lead edit routes |
| `app/src/app/features/user/core/reports/reports.routes.ts` | modified — apply guard |

**~9 files. No backend changes.** All gating is data-driven from the existing `/users/me` permission list.

## `permissionGuard` signature

```ts
export const permissionGuard = (...required: string[]): CanActivateFn => {
  return (route, state) => {
    const currentUser = inject(CurrentUserService);
    const router = inject(Router);

    // Not logged in → bounce to login with return_url
    if (!currentUser.isAuthenticated()) {
      return router.createUrlTree(['/accounts/login'], {
        queryParams: { return_url: state.url },
      });
    }

    // Owner / admin have all keys; permissionGuard does NOT special-case roles.
    // It only checks the resolved permission set from /users/me.
    const granted = currentUser.permissions();   // Set<string>
    const missing = required.filter(k => !granted.has(k));
    if (missing.length > 0) {
      return router.createUrlTree(['/user/access-denied'], {
        queryParams: { required: missing.join(','), return_url: state.url },
      });
    }
    return true;
  };
};
```

Apply per route via the standalone-routes API:

```ts
// settings.routes.ts
{
  path: 'users',
  loadComponent: () => import('./users/users-page.component').then(m => m.UsersPageComponent),
  canActivate: [permissionGuard('users.read')],
}
```

## Access Denied page

Tailwind-only (matches new-page policy). Contents:

- Large 403 / lock icon
- Headline: "Access denied"
- Body: "This page requires the permission **{required}**. Your role *{currentUser.role.name}* does not include it."
- If `return_url` query param present, show "You were trying to open `<return_url>`. Ask your Owner to grant access if you need it."
- Button: [Back to Dashboard] → `/user/dashboard`
- Footer link: "View my permissions →" → `/user/profile/permissions` (if/when that page lands; otherwise no link)

## Tests

Angular tests are typically deferred per the project's test strategy. Minimum smoke:

```
ng build --configuration development   # clean build, no errors

# Manual:
# 1) Log in as an Employee. Hit /user/settings/users → redirected to /user/access-denied with required="users.read" in the URL.
# 2) Hit /user/leads/<id>/edit → redirected (no leads.write key for Employee).
# 3) Log in as Owner. Hit all guarded routes → all pass.
# 4) Log out. Hit /user/settings/users → redirected to /accounts/login?return_url=/user/settings/users.
# 5) Log in via the bounced redirect → after login, return_url honoured.
```

## Risks

- **Stale permissions in the signal:** `currentUser.permissions()` reads from a refreshable signal. If an Admin's permissions change while their session is open (Owner removes a key from Admin), they continue to have the old key until next `/users/me` refresh. Mitigation: the Roles page's save action triggers `currentUser.reload()` for the editing user. Cross-user staleness (Owner edits Bob's role, Bob's tab still has old perms) is accepted within a short window — re-read on every nav also works but is heavier; leave for a separate hardening step if needed.
- **Backend still authoritative:** route guards prevent the page from rendering but the API never trusts them. Every endpoint stays gated by its `require_permissions(...)` dep on the backend (Phase 1.5/1.6 contract). This step is UX, not security.
- **Return_url open-redirect:** validate `return_url` only allows same-origin paths. Reject `return_url=https://evil.com`. Standard fix.

## Rollback

Revert the 9 source files. Routes lose their guards; behaviour reverts to "sidebar-hidden but URL-typeable" — same as before this step.

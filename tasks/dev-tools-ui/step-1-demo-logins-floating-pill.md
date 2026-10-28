# Step 1 — Demo logins floating pill

**Goal:** Move the DR.2 "Test logins" dropdown out of the login card and into a small floating pill anchored to the bottom-right of every screen in dev mode. Production builds do not render or bundle the component.
**Track:** Dev Tools UI
**Status:** COMPLETED
**Depends on:** DR.2 (the inline dropdown this step relocates). If DR.2 hasn't shipped yet, this step subsumes DR.2's work — mark DR.2 Superseded in that case.

---

## Scope

Pure frontend relocation:

1. New `DemoLoginsPillComponent` rendered at the **app shell level** (so it's visible on login, register, dashboard, settings — everywhere in dev).
2. The component is wrapped in `@if (environment.showDevTools)` so it tree-shakes out of prod.
3. The pill itself is a small fixed-position button (bottom-right, `16px` from each edge). Clicking it opens a popover with the four demo presets from DR.2.
4. **On the login page** — picking a preset still auto-fills the form (current DR.2 behaviour), via a shared signal/service.
5. **While authenticated** — picking a preset performs a logout → login → navigate-to-dashboard chain. Acceptable to keep this minimal (call existing auth service methods sequentially).
6. The inline dropdown markup is removed from `login.component.html`. The `selectedOrgSlug` signal stays in `login.component.ts` because the submit handler still reads it.

## Communication between pill and login form

Tiny shared service `DemoPresetBus` (Angular `InjectionToken` or simple `@Injectable({ providedIn: 'root' })`):

```ts
@Injectable({ providedIn: 'root' })
export class DemoPresetBus {
  private readonly _selected = signal<DemoPreset | null>(null);
  readonly selected = this._selected.asReadonly();
  apply(preset: DemoPreset) { this._selected.set(preset); }
  clear() { this._selected.set(null); }
}
```

- **Pill** writes to it via `bus.apply(preset)`.
- **Login component** reads `bus.selected()` via an `effect()` that patches the form whenever a preset comes in.
- **Authenticated screens** consume `bus.selected()` to drive the logout → login chain.

This avoids `@Output`/`@Input` plumbing for a component that lives several layers away from the login form in the tree.

## UI shape

**Collapsed pill:**

```
                                              ┌──────────────────┐
                                              │  🛠 Demo logins  │
                                              └──────────────────┘
```

- Fixed position bottom-right, `16px` from each edge.
- `z-index: 50` so it sits above Material overlays but below toast/snackbar (`9999`).
- Tailwind: `fixed bottom-4 right-4 rounded-full bg-slate-900 text-white text-sm px-4 py-2 shadow-lg hover:bg-slate-800`.

**Expanded popover (on click):**

```
┌─────────────────────────────────────┐
│  🛠 Demo logins             [×]     │
├─────────────────────────────────────┤
│  ▸ Core CRM — Admin                 │
│  ▸ Core CRM — Owner                 │
│  ▸ Core CRM — Employee              │
│  ▸ Furniture CRM — Admin            │
└─────────────────────────────────────┘
```

- Each row clickable; on click → `bus.apply(preset)` + close popover.
- Outside-click closes the popover.
- Header shows the current `selectedOrgSlug` ("Active org: core-demo") under the title so the dev knows which slug the next submit will use.

## Env flag

If `environment.showDevTools` doesn't already exist:

```ts
// app/src/environments/environment.ts
export const environment = {
  production: true,
  showDevTools: false,
  // ...
};

// app/src/environments/environment.development.ts
export const environment = {
  production: false,
  showDevTools: true,
  // ...
};
```

Verify Angular's `fileReplacements` config in `angular.json` swaps these on build.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/dev-tools/demo-logins-pill.component.ts` | created |
| `app/src/app/features/dev-tools/demo-logins-pill.component.html` | created |
| `app/src/app/features/dev-tools/demo-logins-pill.component.scss` | created (or inline styles via Tailwind only — pick one) |
| `app/src/app/features/dev-tools/demo-preset-bus.service.ts` | created |
| `app/src/app/features/dev-tools/demo-presets.ts` | created — moves the 4-preset array out of `login.component.ts` |
| `app/src/app/app.component.html` | modified — add `@if (environment.showDevTools) { <app-demo-logins-pill /> }` |
| `app/src/app/app.component.ts` | modified — import the env, register component import |
| `app/src/app/features/accounts/login/login.component.ts` | modified — drop `demoPresets` array; subscribe to `DemoPresetBus.selected` via `effect()`; keep `selectedOrgSlug` signal |
| `app/src/app/features/accounts/login/login.component.html` | modified — remove the inline dropdown `<div>` block |
| `app/src/environments/environment.ts` | modified — add `showDevTools: false` (if missing) |
| `app/src/environments/environment.development.ts` | modified — add `showDevTools: true` (if missing) |

**~9–11 files. No backend. No migrations.**

## Plan

1. Create `app/src/app/features/dev-tools/` folder. Add `demo-presets.ts` with the 4-row preset array + `DemoPreset` interface (copy from DR.2's `login.component.ts`).
2. Add `DemoPresetBus` service (signal-based, root-provided).
3. Build `DemoLoginsPillComponent` (standalone, OnPush) — pill button + popover with preset list. Inject `DemoPresetBus`, call `apply(preset)` on click.
4. Inject component into `app.component.html`, env-gated.
5. In `login.component.ts`:
   - Remove the `demoPresets` array + `applyPreset()` method.
   - Inject `DemoPresetBus`. Add an `effect(() => {...})` that reacts to `bus.selected()` — patches the form + updates `selectedOrgSlug`.
6. In `login.component.html`:
   - Delete the entire inline test-logins block.
7. Verify `environment.showDevTools` flag exists in both env files (add if missing).
8. Smoke against `ng serve` (pill visible) and `ng build --configuration production` (pill absent from output).

## Tests

Angular tests deferred per project policy. Smoke is the gate:

```
# Dev:
ng serve
# 1. /accounts/login → no inline dropdown visible
# 2. Pill in bottom-right → click → popover with 4 presets
# 3. Click "Core CRM — Admin" → form auto-fills email + password; "Active org" caption updates to core-demo
# 4. Submit → log in as admin@core-demo.local → land at /user/dashboard
# 5. Pill still visible on dashboard. Click "Core CRM — Owner" → logged out + back to login + form pre-filled with owner credentials
# 6. /accounts/admin-login → no pill bleed; no inline dropdown either (matches DR.2 contract)

# Prod build:
ng build --configuration production
# 1. Open dist/.../index.html → no <app-demo-logins-pill> in DOM
# 2. grep -r "admin@core-demo.local" dist/ → no matches (tree-shaken out)
# 3. Sanity: /accounts/login still works in the built artefact
```

## Risks

- **Pill overlaps page chrome:** sticky footer, floating action buttons, chat widgets could collide. Mitigation: bottom-right is conventional for dev tools; if collision arises, allow drag-to-reposition in a follow-up. Don't pre-build that.
- **Auth state during preset-switch when already logged in:** the simplest implementation is `logout() → patchForm() → navigate('/accounts/login')` and let the dev click submit. Tempting to auto-submit, but auto-submit while a request is in flight is fiddly. Recommend the click-submit version for v1.
- **`effect()` re-runs:** the bus signal change → form patch effect. Make sure `effect()` is `allowSignalWrites: true` if it writes to other signals, or use `untracked()` correctly. Standard Angular gotcha; mention in code review.
- **Storybook / Cypress:** if those exist, the pill renders in those environments too unless `showDevTools` is overridden. Set it to `false` in those environments' configs. (Confirm during implementation whether either exists.)
- **Accessibility:** the popover needs keyboard support (Esc to close, Tab cycles through presets, Enter activates). Use `cdkOverlay` from `@angular/cdk` if it's already a dep; otherwise a small `(document:keydown.escape)` listener suffices.

## Rollback

Revert the modified files; delete the new `dev-tools/` folder; revert env flag if added. Login page returns to its current DR.2 state (inline dropdown).

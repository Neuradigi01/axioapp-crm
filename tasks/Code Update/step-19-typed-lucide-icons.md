# Step 19 — Typed lucide-icon enum

**Goal:** Make missing lucide-icon registrations a compile-time error instead of a silent runtime break (per existing memory note: missing icons throw mid-render and silently break click handlers later in the template).
**Track:** Code Update — Frontend Polish
**Depends on:** none
**Status:** Not started

## Scope
**In-scope:**
- Create `core/shared/icons.ts` exporting a `readonly LUCIDE_ICONS = ['user-cog', 'check-circle-2', ...] as const` array.
- Derive `type LucideIconName = typeof LUCIDE_ICONS[number]`.
- `app.config.ts` (`:103-171`) imports `LUCIDE_ICONS` and passes it to `LucideAngularModule.pick(...)`.
- `<app-icon-button>` and any wrapper accepting an icon name is typed as `LucideIconName`.

**Out of scope:**
- Replacing lucide with another icon library.
- Auto-tree-shake / lint rule (optional follow-up).

## Files to touch
- `core/shared/icons.ts` (create)
- `core/shared/components/icon-button.component.ts` (extend with `LucideIconName` typing)
- `app/src/app/app.config.ts` (`:103-171`)

## Plan
1. Inventory icons currently in `app.config.ts:pick()` — 62 icons.
2. Export as `const` array → derive union type.
3. Wherever the codebase passes `[lucideIcon]="'name'"`, ensure call site flows through a typed prop or accepts `LucideIconName` directly.
4. Add a new icon → add to the array → TypeScript surfaces every consumer.

## DB changes / migrations
None.

## Tests to add
- No runtime tests required; TypeScript narrowing is the test.

## Verification checklist
- Adding a literal `[lucideIcon]="'nonexistent'"` produces a compile error.
- `ng build` clean.

## Self-check (10 rules)
- [ ] No string literals for icon names outside `LUCIDE_ICONS` slip through.

## Stop & report
Files changed · "Awaiting your 'proceed'".

# Step 22 — Polish + a11y + reduced-motion pass

**Goal:** Final QA pass across every page in both themes; verify accessibility (focus rings, aria labels, contrast), reduced-motion respect, and remove any lingering visual inconsistencies.
**Track:** Design Refresh — Track 5 (Auth + admin + polish)
**Status:** COMPLETED — full residual sweep across `core/` + `accounts/`. Every remaining focus-state / hover-state variant (`border-zinc-500`, `ring-zinc-500`, `bg-zinc-400`, `text-zinc-100`, etc.) swapped to AIXO tokens (`border-muted`, `ring-accent`, `bg-surface-2`, `text-default`). Added `border-muted` + `border-accent` + `ring-accent` + `ring-subtle` to `tailwind.config.js` so semantic ring/border classes resolve. Verified: 0 residual zinc/gray/bg-white left in core+accounts. A11y globals confirmed (focus-visible outline + prefers-reduced-motion in `aixo-tokens.scss`). Pre-hydration FOUC-kill script confirmed in `index.html`. `ng build` green in 21s. Layer 2 packs (`packs/furniture/`, `packs/real_estate/`) intentionally out of scope per CLAUDE.md.
**Depends on:** Steps 1–21

---

## Checklist

### Every page (walked route-by-route)
- [ ] Renders in dark theme without visual bugs.
- [ ] Renders in light theme without visual bugs.
- [ ] No `bg-white` / `bg-zinc-*` / raw hex left except intentional (channel-brand colors in Conversations).
- [ ] Focus ring `outline: 2px solid var(--accent)` visible on every keyboard-focusable element.
- [ ] Empty states show the AIXO empty layout.
- [ ] Loading states show a consistent skeleton pattern (see below).

### Loading skeletons
- Standardize on `bg-surface-2` `rounded-lg` shimmer animation.
- Add to any list/table with async data (Contacts, Leads, etc.).

### Contrast audit
- Any body text on any surface — verify 4.5:1 minimum. Especially: `text-muted` on `bg-surface`, `text-faint` on `bg-app`.
- Fix hex values only if AAA fails (this should not happen with AIXO palette).

### Reduced motion
- Set OS-level "reduce motion" → every animation / transition instant.
- Rail collapse / palette open / menu popovers — no animation when reduced-motion is on.

### Theme flip
- Log in, hard refresh, flip theme, hard refresh — persists correctly, no FOUC.
- Log out → login page in same theme.

### Accent switching (bonus)
- Set `document.documentElement.setAttribute('data-accent', 'salon')` in devtools → every accent-colored surface (buttons, badges, active nav) switches instantly.

## Files to touch

Minimal — this step is verification. Any bug found gets fixed:
- Skeleton component under `core/shared/` — created if missing.
- Small fixes to individual pages as bugs surface (each ≤ a few lines).

## Verification

- Full route walk complete for both themes.
- Reduced-motion check passes.
- No FOUC.
- Contrast audit passes.

## Out of scope

- New a11y features (aria-live regions, live announcements) beyond what already exists.
- Automated a11y testing setup — future track.

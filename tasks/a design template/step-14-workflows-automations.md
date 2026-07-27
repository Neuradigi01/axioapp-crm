# Step 14 — Workflows + Automations refresh

**Goal:** Restyle the Workflows module (list + flowchart builder) and the Automations module (list + single-trigger builder).
**Track:** Design Refresh — Track 4 (Page pass)
**Status:** Pending
**Depends on:** Steps 1, 5, 6, 7

---

## AIXO patterns

### Workflows list
- Card grid: workflow name + category chip + status pill (Draft / Active / Paused) + stats mini-row (enrolled / completed / conversion mono) + toggle switch + "Open →".

### Workflow flowchart builder
- Full-height canvas, `bg-app`, dotted grid pattern `background-image: radial-gradient(circle, var(--border) 1px, transparent 1px); background-size: 24px 24px`.
- Node card: `bg-surface` `border-subtle` `rounded-xl` 12px, min-w-220, p-3. Header: node-type icon + name (font-display 600 13px). Body: description 12.5px text-muted. Connection ports as 8px dots on top/bottom, accent bg.
- Selected node: 2px `border-accent`.
- Palette (right side): `bg-surface-2` `border-subtle` `rounded-xl`, list of draggable node types grouped by category (Triggers / Conditions / Actions / Delays).
- Toolbar top: name (editable inline), Save button, Test-run button, Preview matched events button, Deploy toggle.

### Automations list
- Same card grid as Workflows.

### Automation single-trigger builder
- Full page, three vertical cards: **Trigger** (event picker + filters) → **Conditions** (custom fields dropdown + operator + value) → **Actions** (list of action cards). Each card `rounded-2xl` p-5.
- "+ Add condition" and "+ Add action" buttons at the bottom of their respective cards.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/workflows/*/*.{ts,html,scss}` | modified |
| `APP/src/app/features/user/core/automations/*/*.{ts,html,scss}` | modified |

**Split into two commits (workflows / automations) — each ~5–8 files.**

## Verification

- Workflows list + builder restyled.
- Automations list + builder restyled.
- Canvas grid visible in both themes.
- Flowchart connections still render (SVG edges use `stroke: var(--border)` / `stroke: var(--accent)` when selected).

## Out of scope

- Node rendering engine.
- Backend trigger/action registry.

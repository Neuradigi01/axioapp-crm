# Step 1 — Display-only: assignee badge on list + sender pill on outbound messages

**Goal:** Surface the two pieces of accountability information the backend already records — *who owns this thread* and *who sent each outbound message* — as read-only visual elements in the Conversations page. No PATCH calls in this step; just display.
**Track:** Update Conversations Page
**Status:** COMPLETED — 2026-06-12. 6 files modified (5 spec'd + 1 shared util). Conversations page now loads the staff list once at construct (`StaffApiService.list()` → `Map<string, StaffListItem>`); the map is exposed as a `staffById` signal and plumbed to both children. List rows render an assignee avatar (initials in the deterministic palette from `shared/owner-color.util.ts`) next to the channel chip — unassigned threads show `·` in grey. Thread header carries the same avatar + full name in a pill (read-only — Step 2 will make it clickable). Outbound message bubbles get a small sender avatar in the bottom-right corner (`absolute -bottom-1 -right-1`) showing the rep's initials, with the full name + timestamp in a hover tooltip; bot-emitted messages (sender_user_id = NULL) render a `lucide:bot` icon instead. Reused `ownerColor(userId)` from `shared/owner-color.util.ts` so the same staff member gets the same colour across leads kanban / appointments calendar / conversations — no palette duplication. Added a sibling `staffInitials(fullName)` helper to the same util for consistency. The staff load failure is non-fatal — badges degrade to `?` + grey palette so the page stays usable if `/api/v1/staff` is down.
**Depends on:** None (backend already provides `assigned_to_id` on conversations and `sender_user_id` on messages).

---

## Scope

In-scope:

- Add a small **assignee badge** (initials in a colored circle, OR a grey empty circle for unassigned) to each conversation row in [`conversation-list.component.html`](APP/src/app/features/user/core/conversations/conversation-list.component.html).
- Add the **same assignee badge + a name pill** to the top of the thread header in [`chat-thread.component.html`](APP/src/app/features/user/core/conversations/chat-thread.component.html). Read-only in this step; clicking it does nothing yet. Step 2 wires the reassign behavior.
- Add a **sender pill** to the bottom-right of every outbound message bubble in `chat-thread.component.html`. Show the sending rep's initials. Hover shows full name + send timestamp tooltip.
- Resolve `assigned_to_id` / `sender_user_id` to staff names by **loading the staff list once** at page mount via the existing `GET /api/v1/staff` endpoint (already exposed by [`core/staff/router.py:48`](API/src/app/core/staff/router.py#L48)). Cache as a Map<uuid, StaffListItem> on the page component for O(1) lookup.
- If `sender_user_id` is null on an outbound message (e.g. AI-sent or webhook bot), render a small bot icon instead of initials.
- Match the visual treatment used in the **leads list / kanban cards** — same circle size, same color palette (deterministic hash → one of ~8 background colors).

Out of scope:

- No PATCH / reassign behavior yet — Step 2 owns that.
- No filter chip — Step 3 owns that.
- No new shared component (we don't extract `<app-assignee-badge>` here; we inline the markup. If a second module ever needs the same badge, we'll extract then).
- No backend changes. Staff endpoint already exists.
- No layout / component restructuring. Pure additive visuals.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/conversations/conversations.page.ts` | modified — load the staff list once at construct (`StaffApiService.list()`), expose a `staffById: Signal<Map<string, StaffListItem>>` for children. |
| `APP/src/app/features/user/core/conversations/conversation-list.component.ts` | modified — accept `staffById` as an `@Input()`; expose a `getInitials(id: string | null)` + `getBgClass(id: string | null)` helper. |
| `APP/src/app/features/user/core/conversations/conversation-list.component.html` | modified — render the badge on each row, right side after the channel chip. |
| `APP/src/app/features/user/core/conversations/chat-thread.component.ts` | modified — accept `staffById` as an `@Input()`; expose lookup helpers. |
| `APP/src/app/features/user/core/conversations/chat-thread.component.html` | modified — render the header badge + name pill (read-only), and the sender pill on each `direction='out'` message bubble. |

**5 modified files. 0 created. 0 backend changes.** Within rule-8 budget.

## Plan

1. **Load the staff list.** In `conversations.page.ts` constructor, call `inject(StaffApiService).list()` once. Build a `Map<string, StaffListItem>` (`id → row`). Expose as a `signal`. The list is small (org's full staff) and rarely changes — no need to refresh per request.
2. **Plumb `staffById` down** as an `@Input()` to `<app-conversation-list>` and `<app-chat-thread>` from `conversations.page.html`. Both children read from it for badge/pill rendering.
3. **Inline helpers** (place on each child component, ~6 lines each):
   ```ts
   protected initials(id: string | null): string {
     if (!id) return '';
     const s = this.staffById?.()?.get(id);
     if (!s) return '?';
     const parts = (s.full_name ?? '').trim().split(/\s+/);
     return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase();
   }
   protected bgClass(id: string | null): string {
     if (!id) return 'bg-zinc-200 text-zinc-500';
     const hash = Array.from(id).reduce((a, c) => a + c.charCodeAt(0), 0);
     const palette = ['bg-rose-100 text-rose-700', 'bg-amber-100 text-amber-700',
       'bg-emerald-100 text-emerald-700', 'bg-sky-100 text-sky-700',
       'bg-indigo-100 text-indigo-700', 'bg-fuchsia-100 text-fuchsia-700',
       'bg-cyan-100 text-cyan-700', 'bg-lime-100 text-lime-700'];
     return palette[hash % palette.length];
   }
   ```
   (Copy/match whatever palette the leads kanban already uses, so the same staff member gets the same color across modules.)
4. **List row badge** — a single `<span>` after the channel chip in the row's right-side cluster:
   ```html
   <span [class]="'inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-medium ' + bgClass(c.assigned_to_id)">
     {{ initials(c.assigned_to_id) || '·' }}
   </span>
   ```
5. **Thread header badge + name pill** — at the top of `chat-thread.component.html`, alongside the contact's display name:
   ```html
   @let assigneeId = thread().conversation.assigned_to_id;
   @let assignee = assigneeId ? staffById().get(assigneeId) : null;
   <span [class]="'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ' + bgClass(assigneeId)">
     <span class="inline-flex h-4 w-4 items-center justify-center rounded-full bg-white/40 text-[9px] font-semibold">
       {{ initials(assigneeId) || '·' }}
     </span>
     {{ assignee?.full_name ?? 'Unassigned' }}
   </span>
   ```
6. **Sender pill on outbound messages** — inside the existing outbound-bubble `<div>`, bottom-right:
   ```html
   @if (msg.direction === 'out') {
     <span
       [title]="(staffById().get(msg.sender_user_id ?? '')?.full_name ?? 'Bot') + ' • ' + msg.sent_at"
       [class]="'absolute -bottom-1 -right-1 inline-flex h-4 w-4 items-center justify-center rounded-full ring-2 ring-white text-[9px] font-semibold ' + bgClass(msg.sender_user_id)"
     >
       @if (msg.sender_user_id) {
         {{ initials(msg.sender_user_id) }}
       } @else {
         <lucide-icon name="bot" class="h-2.5 w-2.5"></lucide-icon>
       }
     </span>
   }
   ```
   Position the outbound bubble container as `relative` so the pill clings to its corner.

## DB changes / migrations

**None.**

## Tests

No new pytest. Existing component logic isn't changed; visual additions don't change API contracts.

## Smoke

```
1. Open /user/conversations.
2. Pick a thread that has assigned_to_id set in the DB. Confirm:
   - The row shows the assignee's initials in a colored circle.
   - The thread header shows the same initials + full name in a pill.
3. Pick a thread that does NOT have an assignee. Confirm:
   - The row shows an empty grey circle.
   - The thread header shows "Unassigned" in a grey pill.
4. Inside any thread, find an outbound message you sent. Confirm:
   - Your initials appear in the bottom-right of the bubble.
   - Hover shows your full name + the timestamp.
5. Find an outbound message where sender_user_id IS NULL (rare — only AI auto-replies or bot-emitted). Confirm:
   - A bot icon appears instead of initials.
```

Browser-side via the IDE Simple Browser against your local dev server, or have Ajay click through their own inbox.

## Risks

- **Staff list size for very large orgs.** The endpoint returns every staff row at page mount. If a future org has 1000+ staff this becomes wasteful. Mitigation: the endpoint already paginates the staff page UI — if it returns the full list on `/staff` GET, that's a pre-existing constraint, not introduced here. Flag for a later optimization track.
- **Color palette drift.** If `leads.page.ts` uses a different palette than what's coded here, the same staff member will look different across modules. Mitigation: copy the palette + hash function verbatim from leads. If extraction into a `shared/staff-color.util.ts` is wanted, do it in a follow-up cleanup.
- **Missing staff record for an `assigned_to_id`.** If a thread is assigned to a user who was later soft-deleted, the lookup returns null. Mitigation: render the badge with `'?'` initials and `'Unknown user'` in the pill rather than crashing.

## Self-check (10 rules)

- [ ] Rule 1: No `core/` → `packs/` imports added.
- [ ] Rule 2: No DB changes.
- [ ] Rule 3: Custom fields engine untouched.
- [ ] Rule 4: No new form fields.
- [ ] Rule 5: Sidebar registry untouched.
- [ ] Rule 6: Permissions registry untouched.
- [ ] Rule 7: `pack.yaml` untouched.
- [ ] Rule 8: 5 files modified, ~120 lines net.
- [ ] Rule 9: Stop and report; await "proceed" before Step 2.
- [ ] Rule 10: No TODOs. Helper functions and markup are complete; nothing deferred.

## Stop & report

```
Step 1 — Update conversations page: assignee badge + sender pill

Files changed:
- APP/.../conversations.page.ts (load staff list, expose staffById signal)
- APP/.../conversation-list.component.{ts,html} (badge on each row)
- APP/.../chat-thread.component.{ts,html} (header badge/pill + outbound sender pill)

What you can verify:
- /user/conversations renders assignee initials on every list row
- Thread header shows assignee name + initials (or "Unassigned")
- Outbound message bubbles show sender initials in the bottom-right
- Bot icon shown for sender_user_id = NULL

Tests added: none — pure visual additions, no contract change.

Self-check: 10 rules, all green.

Awaiting your "proceed" before Step 2.
```

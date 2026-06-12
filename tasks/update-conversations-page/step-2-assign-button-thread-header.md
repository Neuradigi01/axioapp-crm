# Step 2 — Assign / reassign from the thread header (reuse `shared/reassign-modal`)

**Goal:** Make the assignee pill in the thread header (built in Step 1) **clickable**. Clicking opens the existing `shared/reassign-modal` component, which lets the user pick a staff member (or "Unassign") and PATCHes `assigned_to_id` on the conversation. After the PATCH succeeds the page updates without reload.
**Track:** Update Conversations Page
**Status:** Pending
**Depends on:** Step 1 — assignee badge already renders read-only in the thread header.

---

## Scope

In-scope:

- Wire a click handler on the thread-header assignee pill that opens [`shared/reassign-modal`](APP/src/app/features/user/core/shared/reassign-modal/reassign-modal.component.ts).
- Adapt the modal's open call so it returns either a staff `user_id` (assign / reassign) or `null` (unassign).
- On modal-close with a value, call `conversationsApi.patch(conversationId, { assigned_to_id })` — the API and method already exist.
- On success, update `detail.conversation.assigned_to_id` + the matching row in the list signal, so the badge re-renders instantly. Standard optimistic-then-confirm shape — match what `onSendText` already does in [`conversations.page.ts:97-152`](APP/src/app/features/user/core/conversations/conversations.page.ts#L97-L152).
- On error, surface via the existing `loadError` signal ("Could not update assignee.") — same error pattern as `onSendText` and `onToggleAi`.
- Permission gate: only render the click target if the user has `conversations.write`. Reads-only sessions still see the read-only pill from Step 1.

Out of scope:

- **No new modal component.** Reuse `shared/reassign-modal` as-is. If its API isn't quite right for the unassign case, prefer extending its input contract over forking.
- **No backend changes.** `PATCH /api/v1/conversations/{id}` with `{ assigned_to_id: uuid | null }` already exists per [`router.py:120-130`](API/src/app/core/conversations/router.py#L120-L130).
- **No audit-log work.** PATCH on the conversation already emits an audit event from the service layer (existing wiring); no extra code here.
- **No filter changes.** Step 3 owns the assignee filter chip.

## Files to touch

| File | Action |
|---|---|
| `APP/.../conversations.page.ts` | modified — add `onReassign(conversationId: string, userId: string \| null)` handler. Plumb to the modal + PATCH + signal updates. |
| `APP/.../conversations.page.html` | modified — bind the handler to `<app-chat-thread>`'s `(reassign)` output. |
| `APP/.../chat-thread.component.ts` | modified — wrap the header pill in a button when user has `conversations.write` permission; emit `(reassign)` output when clicked. Open the `ReassignModalComponent` programmatically. |
| `APP/.../chat-thread.component.html` | modified — switch the read-only pill `<span>` for a `<button>` element (one-line conditional). |

**4 modified files. 0 created. 0 backend changes.**

## Plan

1. **Inspect the existing `shared/reassign-modal` API.** Confirm its input/output shape:
   - Inputs: probably `staffList: StaffListItem[]`, `currentAssigneeId: string | null`, optionally `allowUnassign: boolean`.
   - Output: closes with `{ user_id: string | null } | null` (null = cancel; `{ user_id: null }` = unassign).
   If `allowUnassign` doesn't exist as an input, add it (this is the one upstream contract change). Keep the default `true` for conversations; leads can pass `false` if they want the old behavior.
2. **Wrap the pill in a button** in `chat-thread.component.html`, gated on the permission key:
   ```html
   @if (canWrite()) {
     <button type="button" (click)="openReassign()" [class]="pillClasses(...)">
       <!-- same badge + name markup from Step 1 -->
     </button>
   } @else {
     <span [class]="pillClasses(...)">
       <!-- same badge + name markup from Step 1 -->
     </span>
   }
   ```
   `canWrite()` is a computed from the existing permissions service — copy the pattern used elsewhere on the page (e.g. the AI toggle is also write-gated).
3. **Open the modal** via the existing modal-opening pattern (the codebase uses Angular CDK `Dialog` or an inline-rendered modal, depending on the file — match what `leads.page.ts` does to stay consistent):
   ```ts
   protected openReassign(): void {
     const conv = this.thread()?.conversation;
     if (!conv) return;
     const ref = this.reassignSvc.open({
       staff: this.staffList(),
       currentAssigneeId: conv.assigned_to_id,
       allowUnassign: true,
     });
     ref.afterClosed().subscribe(result => {
       if (!result) return; // cancel
       this.reassign.emit({ conversationId: conv.id, userId: result.user_id });
     });
   }
   ```
4. **Handler on the page** — receives the `{ conversationId, userId }` event, performs the PATCH, updates the signals:
   ```ts
   protected onReassign(ev: { conversationId: string; userId: string | null }): void {
     this.api.patch(ev.conversationId, { assigned_to_id: ev.userId })
       .pipe(takeUntilDestroyed(this.destroyRef))
       .subscribe({
         next: updated => {
           this.items.update(rows => rows.map(r => r.id === updated.id ? updated : r));
           this.detail.update(d => d ? { ...d, conversation: updated } : d);
         },
         error: (err) => this.loadError.set(extractApiError(err) ?? 'Could not update assignee.'),
       });
   }
   ```

## DB changes / migrations

**None.**

## Tests

No new pytest. The behavior is exercised by the existing PATCH endpoint tests; this step just wires a new caller. If the team wants a Cypress / Playwright spec for the click-through, queue it as a separate test-infra task.

## Smoke

```
1. Open /user/conversations as an Owner / Admin / Sales-Senior (anyone with conversations.write).
2. Open a thread → click the assignee pill in the header.
3. The reassign modal opens with the staff list, the current assignee preselected.
4. Pick a different staff member → click Confirm.
5. The pill updates to the new assignee's initials + name.
6. The same row in the left-side list also updates its badge.
7. Open the same thread fresh from URL — assignee is persisted.
8. Now click the pill → modal → Unassign → Confirm.
9. The pill returns to grey "Unassigned"; list row badge becomes empty grey circle.
10. Log in as Sales-Junior (read-only conversations) → the pill is NOT a button; click does nothing. (Step 1's read-only render still applies.)
```

## Risks

- **`shared/reassign-modal` doesn't have `allowUnassign`.** Add it as an optional input with default `true`. Audit the two leads call sites to confirm neither breaks; add the explicit kwarg if either should keep the old behavior.
- **Modal opening pattern differs across the app** (some pages use Angular CDK Dialog, some use bespoke inline overlays). Pick whichever is used in `leads.page.ts` since this track explicitly aligns to leads.
- **Race on the WS auto-refresh.** If a notification fires between the PATCH and the page's signal update, the auto-refresh might briefly overwrite the optimistic state. Match `onSendText`'s pattern — write the PATCH result back authoritatively after the API succeeds; this overrides any stale WS-driven refresh that came in milliseconds earlier.
- **Permission check at the right layer.** Don't rely on the modal to enforce write permission — the page button must hide itself for read-only users. Otherwise the modal opens, user fiddles, hits Confirm, and gets a 403 back from the PATCH. Ugly UX.

## Self-check (10 rules)

- [ ] Rule 1: No `core/` → `packs/` imports added.
- [ ] Rule 2: No DB changes.
- [ ] Rule 3: Custom fields engine untouched.
- [ ] Rule 4: Not a form change.
- [ ] Rule 5: Sidebar registry untouched.
- [ ] Rule 6: Permissions registry untouched (uses existing `conversations.write`).
- [ ] Rule 7: `pack.yaml` untouched.
- [ ] Rule 8: 4 files modified, ~80 lines net.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: No TODOs. PATCH success path, error path, and read-only fallback all wired.

## Stop & report

```
Step 2 — Update conversations page: assign / reassign from thread header

Files changed:
- APP/.../conversations.page.{ts,html}
- APP/.../chat-thread.component.{ts,html}
- (possibly) APP/.../shared/reassign-modal/* — added allowUnassign input

What you can verify:
- Owner clicks assignee pill in thread header → modal opens
- Selecting a staff member updates the list badge + thread pill instantly
- Selecting "Unassign" sets assigned_to_id to NULL; pill goes grey
- Sales-Junior (read-only) sees the pill but cannot click it
- Errors surface through the existing loadError signal

Tests added: none — re-uses the existing PATCH endpoint already covered by backend tests.

Self-check: 10 rules, all green.

Awaiting your "proceed" before Step 3.
```

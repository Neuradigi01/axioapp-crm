# Step 3 — Assignee filter chip — Mine / Unassigned / Specific staff

**Goal:** Add an assignee filter to the conversation list header. Match the convention already used in [`leads.page.ts:165`](APP/src/app/features/user/core/leads/leads.page.ts#L165) — `Mine` (filters to the logged-in user), `Unassigned` (`assigned_to=null`), `All`, and a per-staff option. The selection plumbs into the existing `GET /api/v1/conversations?assigned_to=<value>` API.
**Track:** Update Conversations Page
**Status:** Pending
**Depends on:** Step 1 (staff list already loaded + plumbed) — that loaded `staffById` already; this step reuses it.

---

## Scope

In-scope:

- A new filter chip in [`conversation-list.component.html`](APP/src/app/features/user/core/conversations/conversation-list.component.html) header — third row of filters next to channel + status.
- Four preset modes plus a per-staff selector:
  - **All** — clears the assignee filter
  - **Mine** — `assigned_to=<current_user.id>`
  - **Unassigned** — `assigned_to=unassigned` (matches the leads convention; backend should already treat this as `IS NULL`. If it doesn't, document and let backend land a tiny fix — verify in Step 1 of this step's plan.)
  - **Specific staff** — opens a small picker, sets `assigned_to=<picked_user_id>`
- Wire the picker to the existing `assigned_to` query param on `ConversationListQuery` in [`conversations-api.service.ts:64`](APP/src/app/features/user/core/conversations/conversations-api.service.ts#L64) — no API change needed.
- The new filter combines naturally with the existing channel + status filters — same filter signal, same `reloadList()` debouncing.
- The WS auto-refresh path in [`conversations.page.ts:77-84`](APP/src/app/features/user/core/conversations/conversations.page.ts#L77-L84) keeps respecting the current filter (it already reuses `this.filters()` via `reloadList()` — no change needed).
- Persist the selection in `sessionStorage` so a hard refresh doesn't reset Sales-Junior's "Mine" view. Optional but standard in this codebase — match how leads handles it; skip if leads doesn't persist.

Out of scope:

- No backend changes. If `assigned_to=unassigned` isn't recognized as `IS NULL` on the conversations list endpoint, that's a 5-line backend fix scoped to Step 1 of this step's plan — call it out, do not silently change scope.
- No multi-select. Picking "Specific staff" filters to one staff at a time. Multi-select can be a Tier-2 follow-up if anyone asks.
- No "all assigned to non-me" smart filter.

## Files to touch

| File | Action |
|---|---|
| `APP/.../conversation-list.component.html` | modified — add a third row of filter controls with the four chip options + the staff picker. |
| `APP/.../conversation-list.component.ts` | modified — bind chip clicks to a new `(assigneeChange)` output. Add `currentUserId` and `staffById` as `@Input()`s (one already exists from Step 1; just add `currentUserId`). |
| `APP/.../conversations.page.ts` | modified — wire `(assigneeChange)` to `filters.update(...)` and call `reloadList()`. Set the initial value from `sessionStorage` on construct. |
| `APP/.../conversations.page.html` | modified — pass `[currentUserId]="me().id"` and `(assigneeChange)="onAssigneeFilterChange($event)"` to `<app-conversation-list>`. |
| (verify) `API/.../core/conversations/service.py:list_conversations` | **verify only** — if `assigned_to='unassigned'` doesn't map to `Conversation.assigned_to_id IS NULL`, add the branch. ~5 lines. Confirm before claiming this is "frontend only". |

**4 modified frontend files + 0–1 backend.** Within rule-8 budget.

## Plan

1. **Verify backend `unassigned` semantics.** Read [`core/conversations/service.py:list_conversations`](API/src/app/core/conversations/service.py). If `assigned_to_id == 'unassigned'` is not treated as `Conversation.assigned_to_id IS NULL`, add the branch:
   ```python
   if assigned_to_id == "unassigned":
       filters.append(Conversation.assigned_to_id.is_(None))
   elif assigned_to_id is not None:
       filters.append(Conversation.assigned_to_id == assigned_to_id)
   ```
   Note: the query param type may need to widen from `uuid.UUID` to `str` in the router for this to parse. **If this 5-line backend change is needed, document it explicitly in the report.**
2. **Frontend filter chip markup** — third row of filters in `conversation-list.component.html`:
   ```html
   <div class="grid grid-cols-4 gap-2">
     @for (mode of assigneeModes; track mode.value) {
       <button type="button"
         (click)="setAssignee(mode.value)"
         [class]="'rounded-md border px-2 py-1.5 text-xs ' + (currentMode() === mode.value ? 'border-zinc-500 bg-zinc-100' : 'border-zinc-300 bg-white')">
         {{ mode.label }}
       </button>
     }
   </div>
   @if (currentMode() === 'specific') {
     <select (change)="onPickStaff($event)" class="mt-2 rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-xs">
       <option value="">— Select staff —</option>
       @for (s of staffOptions(); track s.id) {
         <option [value]="s.id">{{ s.full_name }}</option>
       }
     </select>
   }
   ```
3. **Filter state in the component:**
   ```ts
   protected readonly assigneeModes = [
     { value: 'all',         label: 'All' },
     { value: 'mine',        label: 'Mine' },
     { value: 'unassigned',  label: 'Unassigned' },
     { value: 'specific',    label: 'Specific…' },
   ];
   protected readonly currentMode = signal<'all'|'mine'|'unassigned'|'specific'>('all');
   protected readonly specificUserId = signal<string | null>(null);

   protected setAssignee(mode: typeof this.assigneeModes[number]['value']): void {
     this.currentMode.set(mode);
     if (mode !== 'specific') {
       this.specificUserId.set(null);
       this.emitFilter();
     }
   }
   protected onPickStaff(ev: Event): void {
     this.specificUserId.set((ev.target as HTMLSelectElement).value || null);
     this.emitFilter();
   }
   private emitFilter(): void {
     const m = this.currentMode();
     const val = m === 'mine' ? this.currentUserId
              : m === 'unassigned' ? 'unassigned'
              : m === 'specific' ? this.specificUserId() ?? undefined
              : undefined;
     this.assigneeChange.emit(val);
   }
   ```
4. **Page handler** in `conversations.page.ts`:
   ```ts
   protected onAssigneeFilterChange(assigned_to: string | undefined): void {
     this.filters.update(prev => ({ ...prev, assigned_to }));
     sessionStorage.setItem('conversations:assignee', assigned_to ?? '');
     this.reloadList();
   }
   ```
   On constructor, hydrate from `sessionStorage` and seed `filters` once.
5. **Pass `currentUserId`** to the list component via `[currentUserId]="me().id"` in the parent template. `me()` is the existing user signal exposed by the auth service.

## DB changes / migrations

**None.**

## Tests

If the backend tweak in step 1 lands, add one unit assertion in `tests/test_conversations_list.py` (already exists, presumably): `assigned_to='unassigned'` returns only the rows where `assigned_to_id IS NULL`. ~10 lines.

## Smoke

```
1. Open /user/conversations as a user with mixed-ownership threads in your org.
2. Default state: "All" chip active; list shows everything.
3. Click "Mine" → list narrows to threads assigned to the current user.
4. Click "Unassigned" → list narrows to threads with no assignee. Row badges should all be grey.
5. Click "Specific…" → staff selector appears → pick "Priya" → list narrows to threads assigned to Priya.
6. Combine: channel = WhatsApp + assignee = Mine. Confirm both filters compose.
7. Send yourself a test inbound message via WhatsApp while "Mine" is active. Confirm:
   - The list refreshes (WS hook works).
   - If the new conversation isn't assigned to you, it does NOT appear in your view.
   - The notification still fires (bell icon, not the list filter).
8. Hard refresh while "Mine" is active. The filter persists (sessionStorage).
9. As a Sales-Junior with conversations.read only, the chips still work — read-only doesn't block filtering.
```

## Risks

- **Backend semantics for `unassigned`.** If today's endpoint requires a valid UUID and rejects `'unassigned'`, the frontend submission will 400. Verify before plumbing UI; the 5-line backend fix is documented above.
- **Filter persistence collides across orgs.** If the same user logs in / switches between two orgs, the stored "specific user" id from org A is bogus in org B. Mitigation: prefix the `sessionStorage` key with the active `org_id`. One-line change.
- **WS refresh respects filter (and silently hides rows).** A user might be confused when an inbound message arrives but doesn't show in their view. Mitigation: the bell-icon notification already fires regardless of the inbox filter; that path is unaffected. Nothing extra needed in this step.
- **Permission scoping for `Mine`.** A Sales-Junior with `conversations.read` only can filter to "Mine" — but they can also filter to "Specific other staff" and see anyone's queue if backend doesn't restrict. This is a deliberate read-scope decision: managers see everything, juniors see everything (their `conversations.read` is org-wide). If you want stricter scoping (e.g. juniors can only see Mine), that's a separate permission-model change — out of scope here.

## Self-check (10 rules)

- [ ] Rule 1: No `core/` → `packs/` imports added.
- [ ] Rule 2: No DB changes (only verify-and-maybe-tweak backend semantics).
- [ ] Rule 3: Custom fields engine untouched.
- [ ] Rule 4: Not a form change.
- [ ] Rule 5: Sidebar registry untouched.
- [ ] Rule 6: Permissions registry untouched.
- [ ] Rule 7: `pack.yaml` untouched.
- [ ] Rule 8: 4 frontend files + 0–1 backend, ~120 lines net.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: No TODOs. Filter modes, persistence, WS interaction all wired explicitly.

## Stop & report

```
Step 3 — Update conversations page: assignee filter chip

Files changed:
- APP/.../conversation-list.component.{ts,html}
- APP/.../conversations.page.{ts,html}
- (if needed) API/.../core/conversations/service.py:list_conversations — added the IS NULL branch for `assigned_to='unassigned'`
- (if backend change) API/tests/test_conversations_list.py — one assertion

What you can verify:
- /user/conversations shows the four-mode chip row in the list header
- Mine / Unassigned / Specific staff filter the list correctly
- Combines with channel + status filters
- Persists across hard refresh (sessionStorage, org-prefixed)
- WS auto-refresh respects the active filter; notifications bell still fires regardless

Tests added: 1 backend list-filter assertion (if backend touched).

Self-check: 10 rules, all green.

Track closed. The three steps together complete the conversations page accountability surface (badge + reassign + filter). The backend's assigned_to_id and sender_user_id columns are now fully visible and editable from the UI.
```

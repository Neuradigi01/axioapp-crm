# Update Conversations Page

A focused frontend track to surface the **assignment + sender** signals that the Conversations backend already populates but the UI ignores. After this track, a manager can see who owns each thread at a glance, reps can claim or hand off threads from the page, and outbound messages show who from your team sent them.

## Why this exists

The backend already does the work:

- [`tbl_conversations.assigned_to_id`](API/src/app/core/conversations/models.py#L111) — every thread can be assigned to a staff member.
- [`tbl_messages.sender_user_id`](API/src/app/core/conversations/models.py#L159) — every outbound message is tagged with the rep who sent it.
- `PATCH /api/v1/conversations/{id}` accepts `assigned_to_id` for assign / reassign / unassign.
- `GET /api/v1/conversations?assigned_to=<uuid>` filters the list to an assignee.
- [`send_outbound()`](API/src/app/core/conversations/service.py) correctly records `sender_user_id = user.legacy_uuid` on every outbound row.

What the **UI** does not do today (per `conversation-list.component.html` + `chat-thread.component.html`):

| Surface | Today | After this track |
|---|---|---|
| List rows | Channel + last-message snippet only | Channel + last-message + assignee badge |
| Thread header | Phone / handle only | Phone / handle + assignee pill (click to reassign) |
| Outbound messages | All look identical regardless of sender | Each outbound bubble shows the sending rep's initials/avatar |
| Filter chips | Search + Channel + Status | Search + Channel + Status + Assignee (`Mine` / `Unassigned` / specific staff) |

The cost paid on the backend (extra columns, RLS-safe writes, audit trail of who replied) is wasted as long as none of this surfaces.

## What this does NOT do

- **No backend changes.** Models, endpoints, audit events all already exist.
- **No new database tables / no new migration.** Schema is untouched.
- **No auto-routing / round-robin.** That's a separate follow-up — would need a Celery hook on `receive_webhook`. Out of scope here.
- **No internal-notes / quick-reply templates / SLA timers.** Tier-2 items from the gap analysis — separate tracks if you want them.
- **No AI handling settings page.** The toggle exists but the underlying AI worker isn't built (Phase 5.7). Wiring a settings UI in front of a non-existent worker would be dead UI.

## Acceptance criteria

After all 3 steps land:

1. The list rows in `/user/conversations` show a small assignee badge — initials in a colored circle for assigned threads, an empty grey circle for unassigned.
2. The thread header (above the messages, next to the contact name) shows the same badge plus the assignee's name in a pill. Clicking it opens the existing `shared/reassign-modal` and PATCHes `assigned_to_id`.
3. Outbound message bubbles in the chat thread show the sending rep's initials in the bottom-right corner. Hovering the initials shows full name + send time tooltip.
4. The list header gains an Assignee filter chip with three preset modes — `All`, `Mine` (filters to the logged-in user), `Unassigned` (filters to `assigned_to=null`) — plus a "Specific staff" option that opens a staff picker.
5. Switching filter mode triggers `GET /api/v1/conversations?assigned_to=…` and the list updates without a page reload. Combines naturally with the existing channel/status filters.
6. The WebSocket auto-refresh path (already in [`conversations.page.ts:77-84`](APP/src/app/features/user/core/conversations/conversations.page.ts#L77-L84)) keeps working — when a new message lands, the list refreshes respecting the current assignee filter.

## Reuse — what NOT to rebuild

| Already exists | Use it from |
|---|---|
| `shared/reassign-modal` component | [`APP/src/app/features/user/core/shared/reassign-modal/`](APP/src/app/features/user/core/shared/reassign-modal/) |
| Staff list endpoint `GET /api/v1/staff` | Already wired; returns `StaffListItem[]` |
| `Mine / Unassigned / <uuid>` filter convention | [`leads.page.ts:165`](APP/src/app/features/user/core/leads/leads.page.ts#L165) and the leads-page filter chip — copy the shape |
| Avatar / initials styling | Look at leads list rows + kanban cards — same visual treatment |

Reusing these means each step in this track stays small and visually consistent with leads.

## Dependencies

- Backend: `core/conversations`, `core/staff` — both production-ready.
- Frontend: `features/user/core/conversations/*`, `shared/reassign-modal`, `core/staff/staff-api.service`.
- Permissions: existing `conversations.read` / `conversations.write` keys. No new keys.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Display-only: assignee badge on list + sender pill on outbound messages](step-1-assignee-badge-and-sender-pill.md) | Pending | ~3 hrs |
| 2 | [Assign / reassign from the thread header (reuse `shared/reassign-modal`)](step-2-assign-button-thread-header.md) | Pending | ~3 hrs |
| 3 | [Assignee filter chip — Mine / Unassigned / Specific staff (reuse leads convention)](step-3-assignee-filter-chip.md) | Pending | ~3 hrs |

**Total: ~1 day end-to-end.** Each step independently verifiable; pause and report after each per rule 9.

## File budget (rough)

| Area | Files | Notes |
|---|---|---|
| Step 1 | ~3 modified | `conversation-list.component.html/.ts`, `chat-thread.component.html`. Add a tiny `<app-assignee-badge>` widget inline if not extracting. |
| Step 2 | ~2 modified | `chat-thread.component.html/.ts`. Import & wire `ReassignModalComponent`. |
| Step 3 | ~2 modified | `conversation-list.component.html/.ts` + small bump in `conversations.page.ts` to forward the new filter to the API. |

**Total: ~5–7 files modified, 0 new files, 0 backend changes.**

## Self-check against the 10 rules

- ✅ Rule 1: All work in `core/conversations/*` frontend. No `core/` → `packs/` imports added.
- ✅ Rule 2: No DB changes; `org_id` + RLS untouched.
- ✅ Rule 3: Custom fields engine not involved.
- ✅ Rule 4: Dynamic-form contract untouched (no new form fields).
- ✅ Rule 5: Sidebar registry untouched.
- ✅ Rule 6: Permissions registry untouched (`conversations.read/write` already cover the operations).
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: Each step < 5 files / < 200 lines net change.
- ✅ Rule 9: Stop and report after each step; await "proceed".
- ✅ Rule 10: No TODOs. Each step ships its slice complete or doesn't ship.

## After this track

- Multi-rep teams can divide work explicitly instead of relying on "whoever sees it first".
- Managers see ownership at a glance and can spot dropped threads (long-unread unassigned rows).
- Outbound messages carry the audit "who replied" signal all the way to the visual layer.
- The backend's `assigned_to_id` + `sender_user_id` columns stop being silent.

What this track does *not* fix:

- Auto-routing (a thread still has to be claimed manually). Add a dedicated `tasks/conversation-routing/` track if you want round-robin / skill-based.
- Internal notes for handoffs. Separate track.
- WhatsApp template quick-replies. Separate track.

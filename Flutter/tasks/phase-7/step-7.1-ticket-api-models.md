# Step 7.1 — Ticket API Service & Models

> **Status:** PENDING

> **Phase 7: Support Ticket System**

**Prerequisites:** Phase 5 complete (Step 5.3). Can run in parallel with Phase 6.

---

**What to do:**
1. Create `lib/services/ticket_api_service.dart` — ticket API calls
2. Create `lib/models/ticket.dart` — Ticket, TicketDetail, ThreadMessage models (freezed)
3. Create `lib/schemas/ticket_schema.dart` — request DTOs
4. Create `lib/providers/ticket_provider.dart` — providers for ticket list and detail
5. Run `build_runner`

**API methods:**
- `getList(TicketListRequest)` → ApiResponse (paginated)
- `getDetail(int ticketId)` → ApiResponse (ticket + thread)
- `compose(ComposeTicketRequest)` → ApiResponse
- `reply(int ticketId, ReplyTicketRequest)` → ApiResponse
- `uploadAttachment(String filePath)` → ApiResponse (returns stored filename)
- `getAttachmentUrl(String storedName)` → String (download URL)

**Models:**
- `Ticket` — id, subject, status, priority, createdAt, lastReplyAt, replyCount
- `TicketDetail` — id, subject, status, priority, createdAt, thread (list of ThreadMessage)
- `ThreadMessage` — id, message, senderType (User/Admin), senderName, createdAt, attachments
- `TicketAttachment` — id, fileName, storedName, fileSize

**Request DTOs:**
- `TicketListRequest` — search, status, priority, pageIndex, pageSize
- `ComposeTicketRequest` — subject, message, attachments (list of stored names)
- `ReplyTicketRequest` — message, attachments

**Verify:**
- [ ] All models generate correctly
- [ ] API service compiles
- [ ] Providers registered (list with pagination, detail by ID)

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.

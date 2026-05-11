# Phase 3 — Communication & Staff (still core)

**Goal:** Build the universal communication and staff features — walk-ins, basic catalog, staff admin + portal with PIN login, channel-agnostic conversations (with WhatsApp adapter), call center, reviews, marketing campaigns, settings. Still strictly Layer 1 (core); no furniture-specific code.

**Phase completion criteria:** All universal CRM features work end-to-end. Admin can manage staff, conversations work over WhatsApp, call logs and reviews display, campaigns can be created and scheduled. Staff portal works with PIN login.

## Steps

| # | Title | Status |
|---|-------|--------|
| 3.1 | [Walk-ins: backend](step-3.1-walkins-backend.md) | Pending |
| 3.2 | [Walk-ins: frontend](step-3.2-walkins-frontend.md) | Pending |
| 3.3 | [Catalog (basic)](step-3.3-catalog.md) | Pending |
| 3.4 | [Staff module: backend](step-3.4-staff-backend.md) | Pending |
| 3.5 | [Staff module: frontend (admin view)](step-3.5-staff-frontend.md) | Pending |
| 3.6 | [Staff Portal auth (PIN login)](step-3.6-staff-portal-auth.md) | Pending |
| 3.7 | [Staff Portal: frontend](step-3.7-staff-portal-frontend.md) | Pending |
| 3.8 | [Conversations: backend (architecture)](step-3.8-conversations-architecture.md) | Pending |
| 3.9 | [Conversations: WhatsApp adapter](step-3.9-conversations-whatsapp.md) | Pending |
| 3.10 | [Conversations: frontend](step-3.10-conversations-frontend.md) | Pending |
| 3.11 | [Call Center: backend](step-3.11-call-center-backend.md) | Pending |
| 3.12 | [Call Center: frontend](step-3.12-call-center-frontend.md) | Pending |
| 3.13 | [Reviews: backend](step-3.13-reviews-backend.md) | Pending |
| 3.14 | [Reviews: frontend](step-3.14-reviews-frontend.md) | Pending |
| 3.15 | [Campaigns: backend](step-3.15-campaigns-backend.md) | Pending |
| 3.16 | [Campaigns: frontend](step-3.16-campaigns-frontend.md) | Pending |
| 3.17 | [Settings module](step-3.17-settings.md) | Pending |

## Dependencies

- All steps depend on Phase 2 complete.
- 3.2 depends on 3.1 + Step 2.3 (dynamic form).
- 3.5 depends on 3.4.
- 3.7 depends on 3.6.
- 3.9 depends on 3.8.
- 3.10 depends on 3.8 + 3.9 + 2.16 (uses notification WS infra).
- 3.12 depends on 3.11.
- 3.14 depends on 3.13.
- 3.16 depends on 3.15 + 3.8 (reuses channel adapters).

# Phase 5 — Commerce Integrations & AI

**Goal:** Plug the furniture pack into multi-channel commerce (Amazon, Flipkart, Shopify) and turn on the AI features (chatbot, auto follow-ups, virtual staging). Also build the Reviews automation and the live admin dashboard.

**Phase completion criteria:** Multi-channel commerce works (orders flow in from marketplaces). AI chatbot answers in Conversations with override flow. Day-1/3/7 follow-ups fire from Celery beat. AI Virtual Staging produces preview images. Reviews are auto-requested after delivery. Admin dashboard reflects real-time activity.

## Steps

| # | Title | Status |
|---|-------|--------|
| 5.1 | [Marketplace abstraction](step-5.1-marketplace-abstraction.md) | Pending |
| 5.2 | [Amazon adapter](step-5.2-marketplace-amazon.md) | Pending |
| 5.3 | [Flipkart adapter](step-5.3-marketplace-flipkart.md) | Pending |
| 5.4 | [Shopify adapter](step-5.4-marketplace-shopify.md) | Pending |
| 5.5 | [Marketplace frontend](step-5.5-marketplace-frontend.md) | Pending |
| 5.6 | [In-Store QR Marketing](step-5.6-qr-marketing.md) | Pending |
| 5.7 | [AI Chatbot in Conversations](step-5.7-ai-chatbot.md) | Pending |
| 5.8 | [AI Auto Follow-up Schedule](step-5.8-ai-followups.md) | Pending |
| 5.9 | [AI Virtual Staging: backend](step-5.9-virtual-staging-backend.md) | Pending |
| 5.10 | [AI Virtual Staging: frontend](step-5.10-virtual-staging-frontend.md) | Pending |
| 5.11 | [Reviews automation](step-5.11-reviews-automation.md) | Pending |
| 5.12 | [Admin Dashboard overview](step-5.12-admin-dashboard.md) | Pending |

## Dependencies

- All steps depend on Phase 4 complete.
- 5.2/5.3/5.4 depend on 5.1.
- 5.5 depends on 5.1–5.4.
- 5.7 depends on 3.10 (conversations frontend) and 3.8 (channel registry).
- 5.8 depends on Celery beat (Phase 1) + pack manifest follow-up templates (4.1).
- 5.10 depends on 5.9.
- 5.11 depends on 3.13 (reviews) + 3.15 (campaigns) + 4.8 (orders/delivery event).
- 5.12 depends on most prior modules being live (it pulls KPIs, leads, appointments, AI activity).

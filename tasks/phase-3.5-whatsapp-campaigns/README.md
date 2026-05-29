# Phase 3.5 — WhatsApp Campaigns

End-to-end WhatsApp Business Cloud API campaigns: multi-tenant connect → templates → audience targeting → bulk send → delivery tracking → rate-limited async dispatch.

## Status overview

**Progress:** 14 of 15 steps complete (93%)

| # | Step | Layer | Status | Commit |
|---|---|---|---|---|
| 3.5.1 | [WhatsApp Account backend](step-3.5.1-whatsapp-account-backend.md) | Backend | ✅ COMPLETE | — |
| 3.5.2 | [Settings UI card](step-3.5.2-whatsapp-settings-ui.md) | Frontend | ✅ COMPLETE | `6630c45` |
| 3.5.3 | [Adapter rewire (per-org outbound)](step-3.5.3-whatsapp-adapter-rewire.md) | Backend | ✅ COMPLETE | `d332113` |
| 3.5.4 | [Templates sync API](step-3.5.4-whatsapp-templates-sync.md) | Backend | ✅ COMPLETE | uncommitted |
| 3.5.5 | [Template send + picker UI](step-3.5.5-whatsapp-template-send-and-picker.md) | Both | ✅ COMPLETE | uncommitted |
| 3.5.6 | [Dispatch text-vs-template branch](step-3.5.6-dispatch-template-branch.md) | Backend | ✅ COMPLETE | uncommitted |
| 3.5.7 | [Contact groups backend](step-3.5.7-contact-groups-backend.md) | Backend | ✅ COMPLETE | uncommitted |
| 3.5.8 | [Contact groups frontend](step-3.5.8-contact-groups-frontend.md) | Frontend | ✅ COMPLETE | uncommitted |
| 3.5.9 | [Campaign audience builder](step-3.5.9-campaign-audience-builder.md) | Both | ✅ COMPLETE | uncommitted |
| 3.5.10 | [Contact import backend](step-3.5.10-contact-import-backend.md) | Backend | ✅ COMPLETE | uncommitted |
| 3.5.11 | [Contact import frontend](step-3.5.11-contact-import-frontend.md) | Frontend | ✅ COMPLETE | uncommitted (user) |
| 3.5.12 | [Delivery webhook (per-org)](step-3.5.12-delivery-webhook.md) | Backend | ✅ COMPLETE | uncommitted |
| 3.5.13 | [Delivery ticks UI](step-3.5.13-delivery-ticks-ui.md) | Frontend | ✅ COMPLETE | uncommitted |
| 3.5.14 | [Celery async dispatch](step-3.5.14-celery-dispatch.md) | Backend | ✅ COMPLETE | uncommitted |
| 3.5.15 | [Per-org rate limit + 429 backoff](step-3.5.15-rate-limit-backoff.md) | Both | ⏳ Pending | — |

**Legend:** ✅ COMPLETE · 🚧 IN PROGRESS · ⏳ Pending · ❌ Blocked

## What each step delivers

```
Phase 3.5.1 — 3.5.3   →  Multi-tenant connect + per-org outbound
                          (✅ done — Owner can connect WA, send from inbox)

Phase 3.5.4 — 3.5.6   →  Templates pipeline end-to-end
                          (sync → picker → personalised send)

Phase 3.5.7 — 3.5.9   →  Audience: saved groups + 3-mode builder

Phase 3.5.10 — 3.5.11 →  XLSX/CSV bulk contact import

Phase 3.5.12 — 3.5.13 →  Delivery tracking (delivered/read ticks)

Phase 3.5.14 — 3.5.15 →  Production-grade async + rate-limited dispatch
```

## How to work on a step

Each step file follows the same shape:

- **Goal** + **Phase** + **Depends on** + **Status**
- **Scope** (in-scope, out-of-scope)
- **Files to touch** (created + modified)
- **Plan** (5-10 bullets)
- **Verification checklist** (what the user does after I finish)
- **Self-check against the 10 rules**
- **Stop & report** (template for the wrap-up message)
- **Pre-implementation question** (one design call needing user input)

To begin a step:
1. Read the step's `.md` file end-to-end
2. Answer the **Pre-implementation question** (e.g. "a")
3. Say "begin" to me
4. I implement strictly within scope, run tests, stop and report
5. You verify against the checklist
6. Say "proceed" → next step

## After phase 3.5

The 15 steps deliver **MVP-shipping WhatsApp campaigns**. Roughly 70-75% of feature surface vs full-product competitors (ChatJet/WATI/AiSensy). What's deferred to future phases:

| Feature | Phase |
|---|---|
| Chatbot / auto-reply flow builder | 3.6 |
| Cross-campaign analytics dashboard | 3.7 |
| Drip campaigns / message sequences | 3.8 |
| Click-tracking on shortened URLs | 3.9 |
| Template builder UI (vs sync-only) | 3.10 |
| A/B testing for templates | 3.10 |
| Opt-out / STOP keyword + compliance | 3.11 |

These are documented in [`furniture-crm-agent-prompt.md`](../../furniture-crm-agent-prompt.md) as P2 surfaces — to be planned once Phase 3.5 ships and real customer feedback narrows priorities.

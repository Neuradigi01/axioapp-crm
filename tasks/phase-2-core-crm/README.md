# Phase 2 — Core CRM Engine

**Goal:** Build the universal CRM pieces that any vertical pack would also use — custom fields engine, dynamic forms, contacts, activities, tasks, pipelines, leads, appointments, notifications. Strict Layer 1: nothing in this phase imports from `app/packs/`.

**Phase completion criteria:** User can navigate Contacts/Leads/Appointments, customize fields per entity, see activity timelines, manage tasks, drag leads across pipeline stages, book appointments, receive real-time notifications. All forms render dynamically from `custom_field_definitions`.

## Steps

| # | Title | Status |
|---|-------|--------|
| 2.1 | [Custom Fields engine: backend](step-2.1-custom-fields-backend.md) | Pending |
| 2.2 | [Custom Fields engine: frontend](step-2.2-custom-fields-frontend.md) | Pending |
| 2.3 | [Dynamic Form component](step-2.3-dynamic-form.md) | Pending |
| 2.4 | [Contacts: backend](step-2.4-contacts-backend.md) | Pending |
| 2.5 | [Contacts: frontend](step-2.5-contacts-frontend.md) | Pending |
| 2.6 | [Activities timeline: backend](step-2.6-activities-backend.md) | Pending |
| 2.7 | [Activities timeline: frontend](step-2.7-activities-frontend.md) | Pending |
| 2.8 | [Tasks: backend + frontend](step-2.8-tasks.md) | Pending |
| 2.9 | [Pipelines engine: backend](step-2.9-pipelines-backend.md) | Pending |
| 2.10 | [Pipelines engine: frontend](step-2.10-pipelines-frontend.md) | Pending |
| 2.11 | [Leads: backend](step-2.11-leads-backend.md) | Pending |
| 2.12 | [Leads: frontend](step-2.12-leads-frontend.md) | Pending |
| 2.13 | [Appointments: backend](step-2.13-appointments-backend.md) | Pending |
| 2.14 | [Appointments: frontend](step-2.14-appointments-frontend.md) | Pending |
| 2.15 | [Notifications: backend](step-2.15-notifications-backend.md) | Pending |
| 2.16 | [Notifications: frontend](step-2.16-notifications-frontend.md) | Pending |

## Dependencies

- All steps depend on Phase 1 complete.
- 2.2 depends on 2.1; 2.3 depends on 2.1 (reads field defs).
- 2.5 depends on 2.4 + 2.3.
- 2.7 depends on 2.6 + 2.5.
- 2.8 depends on 2.5 (panel on contact detail).
- 2.10 depends on 2.9.
- 2.11 depends on 2.9 + 2.4; 2.12 depends on 2.11 + 2.10 + 2.3.
- 2.14 depends on 2.13 + 2.4.
- 2.16 depends on 2.15.

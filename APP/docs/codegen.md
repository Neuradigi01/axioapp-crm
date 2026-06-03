# Frontend ↔ Backend type codegen

The frontend used to maintain hand-written TypeScript interfaces that
mirrored the backend's Pydantic schemas. When the backend changed a
field, every consumer-FE-file had to be updated manually — and the
mismatch would only surface at runtime as a malformed request or a
`null` access crash.

This project now generates those types automatically from the
backend's `/openapi.json` using
[`openapi-typescript`](https://www.npmjs.com/package/openapi-typescript).

## How to regenerate

```bash
# 1. Make sure the backend is running on http://localhost:8000.
#    From repo root:
cd API && docker-helper.cmd up      # if not already up

# 2. Generate the types:
cd app
npm run generate:api-types
```

This writes to
[`app/src/app/features/user/core/shared/api-types/index.ts`](../src/app/features/user/core/shared/api-types/index.ts).
The file is git-tracked so PRs can review the diff.

Output layout:
- `components['schemas']['ContactOut']` — every Pydantic response model.
- `components['schemas']['ContactCreate']` — every request body.
- `paths['/api/v1/contacts']` — per-endpoint shapes (rarely consumed directly).

## How to consume a generated type

Re-export as a focused alias in the entity's service file:

```ts
// app/src/app/features/user/core/contacts/contacts-api.service.ts
import type { components } from '../shared/api-types';

export type ContactListItem = components['schemas']['ContactListItem'];
export type Contact = components['schemas']['ContactOut'];
export type ContactCreate = components['schemas']['ContactCreate'];
export type ContactUpdate = components['schemas']['ContactUpdate'];
```

Existing consumers (`import { Contact } from './contacts-api.service'`)
keep working — the alias preserves the named export.

## When to regenerate

- **After any backend PR that touches Pydantic schemas.** The CI check
  (TODO — wire `npm run generate:api-types && git diff --exit-code` in
  CI later) will catch drift. Until then, regenerate at the start of
  every FE PR you write.
- **After bumping `openapi-typescript`** in `devDependencies` — output
  format can shift slightly between major versions.

## Migration status

The codegen infrastructure is in place. **Migrating every hand-written
interface to the generated source is an incremental task** — do it
opportunistically when you touch a service file.

**Migrated so far** (canary):
- `ContactListItem` in `contacts/contacts-api.service.ts`

**Still hand-written** (to migrate over time):
- `Contact`, `ContactCreate`, `ContactUpdate`, `ContactDuplicateMatch`,
  `ContactImport*`, `ContactListResponse` in `contacts-api.service.ts`.
- All `Lead*` types in `leads-api.service.ts`.
- All `Task*`, `WalkIn*`, `Appointment*`, `Campaign*`, `Invoice*`,
  `Call*`, `Review*`, `Inventory*`, `CustomOrder*`, `FieldVisit*` types
  in their respective service files.
- Custom-field types (`FieldDef`, `FieldValue`) in
  `shared/dynamic-form/types.ts`.

The hand-written types continue to work; the loop is closed so any new
ones should use the generated source from day one.

## Why we ship a tracked generated file (not `.gitignore` it)

- PRs surface backend schema changes directly in the diff — reviewer
  sees the wire-shape change without checking out and regenerating.
- New contributors don't need a running backend on first build.
- CI can verify the file is up-to-date with a single `git diff` check.

The trade-off: every backend-schema PR will include a regen of this
file. That's the intent — drift is loud, not silent.

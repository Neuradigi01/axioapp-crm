# Coding Standards — Angular App

This document defines standards for writing, organizing, reviewing, and shipping code in this repository.

> **Note:** Component architecture, RxJS, HTTP patterns, styling/theming, and reusability guidelines have been moved to dedicated reference docs. See `AGENT_INDEX.md` section 6 for the on-demand documentation index.

---

## 1) Tech overview and principles

- Framework: Angular (standalone components + feature-based routing, zoneless change detection)
- Language: TypeScript (strict, typed APIs)
- Styles: SCSS with theme files under `src/styles/`
- UI Libraries: Angular Material + PrimeNG
- PWA: Service worker and offline worker present (`ngsw`, `offline-worker.js`)
- Patterns: Feature-first folder structure, lazy loading, route guards, interceptors, signals

Guiding principles:
- Readability over cleverness; optimize for the next maintainer.
- Strong typing and explicitness; avoid `any`.
- Keep components thin; push logic to services.
- Prefer composition over inheritance; keep functions pure where possible.
- Fail fast, handle errors centrally, and surface user-facing errors kindly.

---

## 2) Component, HTTP, RxJS, and styling standards

> **Full details in:**
> - `COMPONENT_REFERENCE.md` — component contract, project structure, naming, RxJS, HTTP/API, routing, schemas, security, performance, accessibility, linting, commenting
> - `THEMING_REFERENCE.md` — CSS/SCSS rules, 3-step token workflow, theme files, forbidden patterns

---

## 3) Git workflow

- Use GitFlow-style branching with PR reviews.
  - Default branch: `dev` (integration). Protected.
  - Long-lived: `main` (stable releases).
- Branch naming:
  - Feature: `feature/<ticket-or-scope>-short-desc` (e.g., `feature/TMPL-01-user-auth`)
  - Bugfix: `bugfix/<ticket>-desc`
  - Hotfix: `hotfix/<ticket>-desc`
  - Release: `release/x.y.z`
  - Chore/Docs: `chore/<scope>-desc`, `docs/<scope>-desc`
- Pull Requests:
  - Keep small and focused; link issues.
  - Include screenshots for UI changes and note a11y impacts.
  - Green CI, lint, tests required.
  - At least 1 reviewer approval.

### Commit messages (Conventional Commits)

- Format: `type(scope): subject`
  - Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`
  - Scope example: `auth`, `dashboard`, `core`, `shared`, `admin`, `user`, `styles`
- Use imperative mood; keep subject <= 72 chars.
- Body: explain what/why; include BREAKING CHANGE if needed.
- Examples:
  - `feat(auth): add two-factor authentication flow`
  - `fix(core): handle 401 by refreshing token once`
  - `refactor(shared): extract file-upload preview service`

---

## 4) Testing

- Unit tests: `*.spec.ts` next to code, minimal but meaningful.
- Aim for coverage thresholds at or above defaults for critical paths (services, guards, pipes).
- Component tests: favor shallow testing with harnesses, test inputs/outputs, DOM roles/selectors.
- Async tests: use `fakeAsync`/`tick` or `waitForAsync` appropriately; avoid microtask leaks.
- E2E (if present): stable data IDs, deterministic, minimal network dependencies.

---

## 5) PWA and offline

- Keep `ngsw-config.json` accurate for asset URLs and data groups.
- `offline-worker.js`: ensure resilient fallbacks for key pages (e.g., `offline.html`).
- Cache versioning strategy: bump on release; avoid stale critical data.

---

## 6) Configuration and environments

- Centralize app runtime settings in `app.settings.ts`; avoid scattering constants.
- Use Angular build configs (`angular.json`) for env-specific replacements.
- Do not hardcode API endpoints; configure via settings or environment files.

---

## 7) Versioning and releases

- Semantic Versioning: `MAJOR.MINOR.PATCH`.
- Release branches `release/x.y.z`; tag `vX.Y.Z` on `main`.
- Maintain a changelog (generated from Conventional Commits if possible).

---

## 8) WebSocket standards

- **Shared WebSocket service:** `src/app/core/services/websocket.service.ts` manages all WS connections — features never create raw `new WebSocket()` directly
- **Event constants:** All WS event types in `src/app/core/constants/ws-events.constants.ts` — never use raw strings
- **Event handler services:** Create dedicated `*-event-handler.service.ts` to subscribe to WS events and route them to feature logic — keeps WS parsing separate from business logic
- **Schemas:** WS message interfaces defined in `src/app/schemas/common.ts` — not inline in components

---

## 9) Code review checklist (quick)

- Naming clear and consistent? No dead code?
- Types strict? No `any` leaks? DTOs mapped to view models?
- Subscriptions cleaned up? Async pipe where possible?
- Errors handled centrally and user-friendly?
- UI accessible and themed correctly? Uses BEM naming?
- Tests added/updated? Lint/format passing?
- Performance: OnPush, trackBy, lazy routes?

---

By following these standards, we keep the codebase consistent, maintainable, and welcoming to contributors. Revisit this document as patterns evolve.

# Component & Architecture Reference — Angular App

> **When to read:** Only when your task involves creating or modifying Angular components, services, pipes, directives, or routing.
> **Prerequisites:** Read `AGENT_INDEX.md` first for golden rules and project structure.

---

## 1. Component Contract

- **Standalone components** and **feature routes**; **lazy load** features
- **Change detection:** `OnPush` required unless a concrete technical reason is provided
- **Zoneless:** App uses `provideZonelessChangeDetection()` — no Zone.js
- **Signals:** Use `signal()`, `computed()`, `input()` for reactive state
- **Inputs/Outputs:** Name inputs as nouns (`userId`), outputs as verb phrases with `EventEmitter` (`submitted`, `closed`). Avoid `onX` prefixes
- **Templates:** Minimal logic; heavy transforms go to pipes/services
- **DI:** Constructor injection for components; `inject()` is acceptable in services/utilities
- **Forbidden:** Inline `template:` or `styles:` arrays in component decorators

### Per-Component Folder Structure

```
src/app/features/<feature>/components/<component>/
  <component>.component.ts
  <component>.component.html
  <component>.component.scss
```

---

## 2. Project Structure

### Feature-First Layout

```
src/app/
  features/<feature>/          — components, services, routes per feature
  shared/                      — reusable UI components, directives, pipes, modules
    components/                — shared components
    pipes/                     — shared pipes
    directives/                — shared directives
    services/                  — shared services
  core/                        — singletons: guards, interceptors, app-wide services, constants
    services/
    guards/
    interceptors/
    constants/
    providers/
  schemas/                     — shared TypeScript interfaces/types (DTOs, view models)
```

### Barrels

Expose stable public APIs via `index.ts` when helpful. Avoid deep relative paths across features.

---

## 3. RxJS and Async Guidelines

- Prefer `async` pipe in templates to auto-manage subscriptions
- In classes, manage subscriptions via:
  - `takeUntilDestroyed()` (Angular 16+), or
  - `takeUntil(this.destroy$)` pattern with a private `Subject<void>`
- Use high-level operators instead of nested subscriptions (`switchMap`, `combineLatest`)
- Use `firstValueFrom` for one-off reads instead of `toPromise`
- Name streams with `$` suffix and keep them `readonly`: `readonly user$ = this.userService.user$;`
- In services, expose `Observable`s; keep `Subject`/`BehaviorSubject` private

### Example: takeUntil Pattern

```ts
private readonly destroy$ = new Subject<void>();
readonly user$ = this.userService.user$;

ngOnInit() {
  this.userService.load().pipe(takeUntil(this.destroy$)).subscribe();
}

ngOnDestroy() {
  this.destroy$.next();
  this.destroy$.complete();
}
```

---

## 4. HTTP/API Design

- All HTTP calls live in dedicated **API services** under `src/app/services/*-api.service.ts` (e.g., `AuthApiService`, `UserApiService`)
- Components MUST NOT call `HttpHelperService` directly — always go through an API service
- Strongly type request/response DTOs using interfaces in `src/app/schemas/`
- Base URL centralized in `app.settings.ts` — `HttpHelperService.buildUrl()` prepends it automatically
- **Auth tokens** are injected by `authInterceptor` (in `core/interceptors/`) — `HttpHelperService` only sets `Content-Type`. Never set auth headers manually in services or components
- **Promise-based pattern:** `HttpHelperService` wraps Angular's `HttpClient` (Observable) with `firstValueFrom()` to return Promises. This simplifies component code (`async/await`) and avoids subscription management. All API services return `Promise<IApiResponse<T>>`

### Service Method Pattern

```ts
// src/app/services/user-api.service.ts
@Injectable({ providedIn: 'root' })
export class UserApiService {
  private readonly http = inject(HttpHelperService);

  getProfile(): Promise<IApiResponse<IUserProfile>> {
    return this.http.Get<IUserProfile>('/user/profile');
  }

  updateProfile(data: IUpdateProfileRequest): Promise<IApiResponse<void>> {
    return this.http.Put('/user/profile', data);
  }
}
```

API service URLs always use a **leading slash** (e.g., `'/user/profile'`, not `'user/profile'`). `HttpHelperService` prepends the base URL automatically.

### Error Handling

- Surface user-friendly messages (see `core/constants/messages.constants.ts`)
- Use `isLoading` signal to reflect loading states
- Prefer non-blocking toasts/snackbars for transient errors; dialogs for destructive actions

---

## 5. Reusability Guidelines

### When to Extract to Shared

If the same component/functionality appears in 2+ locations, extract it to `shared/`.

### Reusable Code Types

| Type | Location | Design Principle |
|------|----------|-----------------|
| Components | `src/app/shared/components/` | Use `@Input()` for customization, `@Output()` for events |
| Pipes | `src/app/shared/pipes/` | Make them pure, handle edge cases |
| Directives | `src/app/shared/directives/` | Clear selector names, configuration inputs |
| Services | `src/app/shared/services/` or `core/services/` | Focused methods, consistent return types |
| Utilities | `src/app/shared/utilities/` or `core/utilities/` | Pure functions, no side effects |

### Common Patterns to Extract

- Date formatting logic -> pipe
- Permission checking -> directive
- Input sanitization -> pipe or directive
- API response transformation -> service method
- Mathematical calculations -> utility functions

---

## 6. Routing — Dynamic Paths via `getRoute()`

Route paths and URLs are **NOT hardcoded** in Angular. They come from the database via the API (`GET /api/routes/config`). The `control_id` is the stable contract between Angular and the DB.

### How It Works

1. **`APP_INITIALIZER`** in `app.config.ts` calls `routesHelper.loadRoutes()` — this populates a module-level cache
2. After loading, `app.routes.ts` is dynamically imported and `Router.resetConfig(appRoutes)` sets the route tree
3. Route files use the standard `export const routes: Routes = [...]` pattern
4. **`getRoute('control_id')`** — a standalone function exported from `routes-helper.service.ts` — returns the full `IRoute` object from the cache
5. Use `.path` in route definitions, `.url` for navigation, `.name` for display
6. Routes **MUST** be loaded from the API on app initialization — `getRoute()` throws if a route is not found (no fallback)

### What Is Static vs Dynamic

| Aspect | Static (in code) | Dynamic (from DB) |
|--------|-------------------|-------------------|
| Route tree structure (parent/child nesting) | Yes | — |
| Component mapping (which component renders) | Yes | — |
| Guards, data, canActivate | Yes | — |
| Route **path** segments | — | Yes, via `getRoute('x').path` |
| Route **URL** (full path) | — | Yes, via `getRoute('x').url` |
| Menu name, icon, order | — | Yes, via `getRoute('x').name`, `.mat_icon`, etc. |
| Access rights / permissions | — | Yes, via JWT `access_rights` |

### Route File Shape (REQUIRED pattern)

Route files use the standard `export const` pattern with `getRoute().path` for paths:

```ts
// feature.routes.ts
import { Routes } from '@angular/router';
import { getRoute } from '@core/services/routes-helper.service';

export const featureRoutes: Routes = [
  {
    path: getRoute('feature_dashboard').path,  // path from DB
    loadComponent: () => import('./dashboard/dashboard.component').then(m => m.DashboardComponent),
  },
  {
    path: getRoute('feature_detail').path + '/:id',  // append params after dynamic path
    loadComponent: () => import('./detail/detail.component').then(m => m.DetailComponent),
  },
];
```

### Navigation in Components (REQUIRED pattern)

**NEVER hardcode URLs** in components or templates. Use `getRoute('control_id').url`:

```ts
// In component TypeScript — for programmatic navigation
import { getRoute } from '@core/services/routes-helper.service';

this.router.navigate([getRoute('user_dashboard').url]);

// As class properties — for template binding
readonly forgotPasswordUrl = getRoute('forgot_password').url;
readonly registerUrl = getRoute('register').url;
```

```html
<!-- In template — use property binding, NOT hardcoded strings -->
<a mat-button [routerLink]="forgotPasswordUrl">Forgot password?</a>

<!-- WRONG — never do this -->
<a mat-button routerLink="/accounts/forgot-password">Forgot password?</a>
```

### App-Level Routes (app.routes.ts)

```ts
import { getRoute } from '@core/services/routes-helper.service';

export const appRoutes: Routes = [
  { path: '', redirectTo: getRoute('accounts').path, pathMatch: 'full' },
  {
    path: getRoute('accounts').path,
    loadChildren: () =>
      import('./features/accounts/accounts.routes').then(m => m.accountsRoutes),
  },
  {
    path: getRoute('user').path,
    loadChildren: () =>
      import('./features/user/user.routes').then(m => m.userRoutes),
  },
  {
    path: getRoute('admin').path,
    loadChildren: () =>
      import('./features/admin/admin.routes').then(m => m.adminRoutes),
  },
  { path: '**', redirectTo: getRoute('accounts').path },
];
```

> **Important:** `app.routes.ts` is dynamically imported in `app.config.ts` (via `await import('./app.routes')`) so that `getRoute()` has data when the const evaluates. Do NOT add a static import of `app.routes.ts` in `app.config.ts`.

### Sub-Module Routing (REQUIRED pattern)

Every sub-feature that has its own children MUST define its routes in its own folder — NEVER inline `children` in the parent route file. Use `loadChildren` to delegate to the sub-module's route file.

```
features/
  user/
    user.routes.ts              ← defines user-level routes
    dashboard/
    profile/
    support/
      support.routes.ts         ← defines support children (compose, inbox, outbox, view-message)
      compose/
      inbox/
      outbox/
      view-message/
  admin/
    admin.routes.ts             ← defines admin-level routes
    dashboard/
    member/
      member.routes.ts          ← defines member children (member-search, member-profile)
    sub-admin/
      sub-admin.routes.ts       ← defines sub-admin children (list, add, edit, access-rights)
    support/
      support.routes.ts         ← defines support children
```

Parent route file delegates via `loadChildren`:

```ts
// user.routes.ts — CORRECT
{
  path: getRoute('user_support').path,
  canActivate: [authGuard],
  data: { role: 'User' },
  loadChildren: () =>
    import('./support/support.routes').then((m) => m.userSupportRoutes),
},

// user.routes.ts — WRONG (do NOT inline children)
{
  path: getRoute('user_support').path,
  children: [
    { path: getRoute('user_support_inbox').path, ... },
    { path: getRoute('user_support_compose').path, ... },
  ],
},
```

### Key Rules

- **NEVER hardcode path strings** in route definitions — always use `getRoute('control_id').path`
- **NEVER hardcode URLs** in components/templates — always use `getRoute('control_id').url`
- **NEVER inline `children`** for sub-features — each sub-module owns its own `*.routes.ts`
- **Route parameters** (`:id`) are appended after the dynamic path: `getRoute('edit_item').path + '/:id'`
- **`control_id` values are stable** — they are the same as the keys in `tbl_routes` and `routes.json`
- Guards in `core/guards/*` — keep lightweight and synchronous when possible
- Page titles via `TitleService`/`app-page-title.strategy.ts`

---

## 7. Data Schemas and Validation

- Define shared interfaces under `src/app/schemas/`
- Keep schemas immutable and descriptive; avoid classes with side effects
- Validate inputs on both client (custom validators) and server; reuse `regex-patterns.ts`
- Interface naming: PascalCase with `I` prefix (e.g., `IUserProfile`)

### Template App Schema Examples

```ts
// src/app/schemas/user.ts
export interface IUserProfile {
  user_id: string;
  first_name: string;
  last_name: string;
  email: string;
  mobile_no: string;
  referral_id: string;
  profile_image: string;
  is_active: boolean;
  two_factor_enabled: boolean;
  joined_on: string;
}

export interface ILoginResponse {
  success: boolean;
  message: string;
  data?: {
    token: string;
    role: string;
    requires_2fa?: boolean;
  };
}

export interface IDashboardStats {
  total_users: number;
  active_users: number;
  inactive_users: number;
  today_registrations: number;
}
```

---

## 8. Security

- Never commit secrets, private keys, or tokens
- Sanitize dynamic HTML; avoid `innerHTML` unless sanitized
- Validate/encode user inputs per `custom-validators.ts` and `regex-patterns.ts`
- Use route guards for role-based access (`admin`, `user`)
- Token handling in interceptor; refresh flows via `refresh.service.ts`

---

## 9. Performance

- Lazy-load routes; optionally preload with `custom-preloading.strategy.ts`
- Memoize expensive computations; avoid heavy work in template expressions
- Use `trackBy` in `*ngFor` and OnPush change detection
- Debounce/throttle rapid user input streams
- Split large bundles and avoid shipping unused polyfills

---

## 10. Accessibility (a11y)

- All interactive elements must be keyboard accessible with discernible text
- Use semantic HTML, ARIA roles only when necessary
- Provide alt text for images; label form controls
- Maintain color contrast across themes; test focus states
- Mobile touch targets: 48px+ minimum

---

## 11. Commenting and Docs

- Write self-documenting code first; add comments when intent isn't obvious
- Use JSDoc for public functions, services, and utilities:
```ts
/**
 * Returns a localized, formatted currency string.
 * @param amount Amount in minor units
 * @param currency ISO 4217 code
 */
```
- TODO/FIXME tags: `// TODO(username): short description`

---

## 12. Linting, Formatting, and Imports

- ESLint rules consistent with Angular style guide
- Formatting: 2 spaces, semicolons, single quotes in TS, double quotes in HTML attributes
- Import order:
  1. Node/Polyfills
  2. Angular libs
  3. Third-party libs
  4. Aliased project paths (`@app/...`, `@shared/...`)
  5. Relative paths

---

## 13. Page Layout System (Filter/Table Pages)

Filter+table pages use `<app-page-layout>` — a shared component that renders a filter card above a data table with pagination. Content is defined ONCE per page via `<ng-template>` refs.

### Architecture

```
Filter page (e.g., user-list)
  --> <app-page-layout>
        |-- Filter card (uses app-form-card internally)
        +-- Table card with pagination
```

### Usage Pattern

```html
<app-page-layout [formGroup]="searchForm" [data]="data" [dataCount]="data_count"
  [isFiltered]="isFiltered" [pageTitle]="'Users'"
  [pageSubtitle]="'View user details'" [tableId]="'tblUsers'"
  (submitEvent)="onSubmit()" (clearEvent)="clearFilters()"
  (pageEvent)="onPageChange($event)" (exportEvent)="exportToCSV()">

  <!-- Required filters -->
  <ng-template #requiredFilters>
    <mat-form-field>
      <mat-label>Search</mat-label>
      <input matInput formControlName="searchTerm" />
    </mat-form-field>
  </ng-template>

  <!-- Optional filters -->
  <ng-template #filters>
    <mat-form-field>
      <mat-label>Status</mat-label>
      <mat-select formControlName="status">
        <mat-option value="All">All</mat-option>
        <mat-option value="Active">Active</mat-option>
        <mat-option value="Inactive">Inactive</mat-option>
      </mat-select>
    </mat-form-field>
  </ng-template>

  <!-- Table header -->
  <ng-template #tableHeader>
    <tr><th>SR#</th><th>User ID</th><th>Name</th><th>Email</th><th>Status</th></tr>
  </ng-template>

  <!-- Table body — rendered for each row; srNo is auto-computed by page-layout from pagination -->
  <ng-template #tableBody let-d let-srNo="srNo">
    <tr>
      <td>{{srNo}}</td>
      <td>{{d.user_id}}</td>
      <td>{{d.first_name}} {{d.last_name}}</td>
      <td>{{d.email}}</td>
      <td>{{d.is_active ? 'Active' : 'Inactive'}}</td>
    </tr>
  </ng-template>
</app-page-layout>
```

### Rules

- Filter fields, table columns, and table body are defined **ONCE** per page via `<ng-template>` refs
- **SR# column is mandatory** for all tables using `<app-page-layout>` — use `let-srNo="srNo"` on the `#tableBody` template to get the auto-computed serial number (accounts for pagination: `pageIndex * pageSize + rowIndex + 1`)
- **Non-filter pages** (profile, settings, forms) use `<app-form-card>` directly — do NOT migrate them to page-layout
- Handles: pagination, export to CSV, collapsible filters, "No records found" message

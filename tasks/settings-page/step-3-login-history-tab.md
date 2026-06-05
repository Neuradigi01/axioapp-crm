# Step 3 — Login history tab: last N sessions + per-row revoke

**Goal:** Surface the legacy `POST /login-history/list` and `POST /login-history/logout-session` endpoints as a Settings tab. Shows the last 50 sign-ins (time, IP, device / user-agent, current session marker) with a Sign-out button on every row except the current one. Gives every staff member a self-service way to spot a stolen session and kill it.

**Depends on:** Step 2 (sits next to Appearance as the third personal tab).

## Why this step exists

The backend already has a complete login-history surface used by the legacy admin panel — paginated list, current-session detection (via `token_id`), per-row revoke, and "log out everywhere" (`GET /login-history/logout`). The FurnitureCRM Settings page has never exposed any of this; staff have no way to see "where am I logged in?" Modern CRMs (and every email client, banking app, etc.) treat this as table-stakes security UX.

This step is pure frontend — wraps the legacy endpoints in a typed Angular service and renders a Tailwind table.

## Files changed

### New
- `APP/src/app/features/user/core/settings/services/login-history-api.service.ts` — typed wrapper around the three legacy endpoints.
- `APP/src/app/features/user/core/settings/tabs/login-history-tab.component.ts`
- `APP/src/app/features/user/core/settings/tabs/login-history-tab.component.html`

### Modified
- `APP/src/app/features/user/core/settings/settings-page.component.ts` — register tab.
- `APP/src/app/features/user/core/settings/settings-page.component.html` — add `@case ('login-history')` branch.

### Tests
- Browser smoke only.

## `login-history-api.service.ts`

```ts
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export interface LoginHistoryEntry {
  token_id: number;
  login_at: string;        // ISO
  ip_address: string | null;
  user_agent: string | null;
  device_label: string | null;  // pre-parsed by the legacy service
  is_current: boolean;
  revoked_at: string | null;
}

export interface LoginHistoryListResponse {
  success: boolean;
  message: string;
  data: {
    entries: LoginHistoryEntry[];
    total: number;
    page_index: number;
    page_size: number;
  };
}

@Injectable({ providedIn: 'root' })
export class LoginHistoryApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/login-history`;

  list(pageIndex = 0, pageSize = 50): Observable<LoginHistoryListResponse> {
    return this.http.post<LoginHistoryListResponse>(`${this.base}/list`, {
      page_index: pageIndex,
      page_size: pageSize,
      match_exact_user_id: true,
    });
  }

  revoke(tokenId: number): Observable<{ success: boolean; message: string }> {
    return this.http.post<{ success: boolean; message: string }>(
      `${this.base}/logout-session`,
      { token_id: tokenId },
    );
  }

  logoutEverywhere(): Observable<{ success: boolean; message: string }> {
    return this.http.get<{ success: boolean; message: string }>(
      `${this.base}/logout`,
    );
  }
}
```

The legacy `POST /list` route reads `user_id` off the JWT when the caller is non-Admin, so passing an empty `user_id` from the client is fine — it gets overwritten server-side. The frontend doesn't need to know its own UUID.

## `login-history-tab.component.ts`

```ts
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';

import { LoginHistoryApiService, LoginHistoryEntry } from '../services/login-history-api.service';
import { extractApiError } from '@core/services/api-error.util';

@Component({
  selector: 'app-settings-login-history-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe],
  templateUrl: './login-history-tab.component.html',
})
export class LoginHistoryTabComponent {
  private readonly api = inject(LoginHistoryApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly entries = signal<LoginHistoryEntry[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly revokingTokenId = signal<number | null>(null);

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.entries.set(res.data?.entries ?? []);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load login history.');
        },
      });
  }

  protected revoke(entry: LoginHistoryEntry): void {
    if (entry.is_current || entry.revoked_at) return;
    this.revokingTokenId.set(entry.token_id);
    this.api.revoke(entry.token_id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.revokingTokenId.set(null);
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.revokingTokenId.set(null);
          this.error.set(extractApiError(err) ?? 'Could not sign out that session.');
        },
      });
  }
}
```

## `login-history-tab.component.html`

```html
<div>
  <div class="mb-3 flex items-center justify-between">
    <p class="text-sm text-zinc-500">
      Recent sign-ins to your account. The session you're using is marked
      <span class="font-medium text-emerald-700">"This session"</span>.
      Sign out of any others if they look unfamiliar.
    </p>
    <button
      type="button"
      class="text-xs text-zinc-600 hover:text-zinc-900"
      (click)="reload()"
    >
      Refresh
    </button>
  </div>

  @if (error(); as err) {
    <div class="mb-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
      {{ err }}
    </div>
  }

  @if (loading()) {
    <div class="rounded-lg border border-zinc-200 bg-white p-6 text-center text-sm text-zinc-500">
      Loading…
    </div>
  } @else if (entries().length === 0) {
    <div class="rounded-lg border border-dashed border-zinc-300 bg-white p-8 text-center text-sm text-zinc-500">
      No login history.
    </div>
  } @else {
    <div class="overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-sm">
      <table class="min-w-full divide-y divide-zinc-200 text-sm">
        <thead class="bg-zinc-50">
          <tr>
            <th class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-zinc-500">When</th>
            <th class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-zinc-500">Device</th>
            <th class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-zinc-500">IP</th>
            <th class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-zinc-500">Status</th>
            <th class="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody class="divide-y divide-zinc-100">
          @for (e of entries(); track e.token_id) {
            <tr [class.bg-emerald-50]="e.is_current">
              <td class="px-3 py-2 text-zinc-800">
                {{ e.login_at | date: 'medium' }}
              </td>
              <td class="px-3 py-2 text-zinc-700">
                {{ e.device_label || e.user_agent || '—' }}
              </td>
              <td class="px-3 py-2 font-mono text-xs text-zinc-600">
                {{ e.ip_address || '—' }}
              </td>
              <td class="px-3 py-2 text-xs">
                @if (e.is_current) {
                  <span class="rounded bg-emerald-100 px-2 py-0.5 text-emerald-800">This session</span>
                } @else if (e.revoked_at) {
                  <span class="rounded bg-zinc-100 px-2 py-0.5 text-zinc-600">Signed out</span>
                } @else {
                  <span class="rounded bg-blue-100 px-2 py-0.5 text-blue-800">Active</span>
                }
              </td>
              <td class="px-3 py-2 text-right">
                @if (!e.is_current && !e.revoked_at) {
                  <button
                    type="button"
                    (click)="revoke(e)"
                    [disabled]="revokingTokenId() === e.token_id"
                    class="text-xs text-rose-600 hover:text-rose-800 disabled:opacity-50"
                  >
                    {{ revokingTokenId() === e.token_id ? 'Signing out…' : 'Sign out' }}
                  </button>
                }
              </td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  }
</div>
```

## `settings-page.component.ts` — register

```ts
type SettingsTab =
  | 'profile' | 'appearance' | 'login-history' | 'notifications'
  | 'store' | 'team' | 'roles' | 'integrations' | 'ai'
  | 'custom-fields' | 'standard-fields' | 'embed';

const TABS: ReadonlyArray<TabDef> = [
  { id: 'profile', label: 'Profile' },
  { id: 'appearance', label: 'Appearance' },
  { id: 'notifications', label: 'Notifications' },
  { id: 'login-history', label: 'Login history' },
  // ... admin tabs (with permission gates) below
];
```

Ordering rationale: personal tabs first (Profile / Appearance / Notifications / Login history), admin tabs after. The first-visible-tab fallback then defaults to Profile for everyone.

## Permission gate

None. Login history is personal data — every user must see their own.

## Tests

Browser smoke:
1. Sign in from two browsers as the same user.
2. Open Settings → Login history in browser A → see two rows, current session marked.
3. Click "Sign out" on browser B's row → next request from browser B 401s and bounces to login.
4. Refresh browser A → that row now shows "Signed out."

## Acceptance

- Tab visible to every authenticated user.
- Current session is clearly marked.
- Revoke works per-row.
- Table is read-safe — no data leaks for other users (backend enforces `match_exact=True` for non-Admin).

## Self-check vs the 10 rules

- ✅ Rule 5, 6 — no module / permission changes.
- ✅ Rule 8 — 5 files; under limit.
- ✅ Rule 10 — ships complete; per-row revoke + current-session marker both work.

## Stop-and-report template

> ✅ Step 3 complete.
> **Files changed:** 5 (3 new, 2 modified).
> **What you can verify:**
> 1. Settings → Login history lists recent sessions with "This session" marker.
> 2. Per-row Sign out kills that token; the affected browser bounces to login on next request.
> 3. Refresh re-fetches the list.
> **Tests added:** browser smoke only.
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 4.

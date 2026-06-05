# Step 4 — Two-factor tab: TOTP / Email OTP / SMS OTP enrol + disable

**Goal:** Surface the legacy `/2fa/*` endpoints as a self-service Settings tab. Staff can enrol TOTP (QR-scan with Google Authenticator / Authy), Email OTP, or SMS OTP from inside the dashboard without having to log out first. Disable requires the legacy action-token confirmation (same `ActionTokenGuard` the existing flow uses).

**Depends on:** Step 3 (sits last among the personal tabs).

## Why this step exists

The 2FA backend ships every method we need:
- `GET /2fa/status` — returns `{ enabled, method }`.
- `POST /2fa/setup-authenticator` — issues a `provisioning_uri` + base32 secret for TOTP.
- `POST /2fa/send-setup-otp` — sends Email / SMS OTP for the enrol flow.
- `POST /2fa/verify-and-enable` — verifies the code + flips the user's 2FA on.
- `POST /2fa/disable` — requires `ActionTokenGuard` (a recent re-auth proof) to prevent a hijacked session from disabling 2FA.

…but the only UI in the FurnitureCRM SPA that exercises any of these lives at `features/accounts/two-factor/` — and that's the **post-login enforcement** path (you can't enrol there unless you've already been challenged). A logged-in user cannot enable, change, or disable 2FA from the dashboard today. This tab closes the gap.

## Files changed

### New
- `APP/src/app/features/user/core/settings/services/two-factor-api.service.ts` — typed wrapper around the 5 endpoints.
- `APP/src/app/features/user/core/settings/tabs/two-factor-tab.component.ts`
- `APP/src/app/features/user/core/settings/tabs/two-factor-tab.component.html`
- `APP/src/app/features/user/core/settings/tabs/two-factor-enrol-modal.component.ts` — small modal for the QR / OTP step.
- `APP/src/app/features/user/core/settings/tabs/two-factor-enrol-modal.component.html`

### Modified
- `APP/src/app/features/user/core/settings/settings-page.component.ts` — register tab.
- `APP/src/app/features/user/core/settings/settings-page.component.html` — add `@case ('two-factor')` branch.

### Tests
- Browser smoke only — the full HTTP / state-machine coverage already exists in the legacy auth tests.

## `two-factor-api.service.ts`

```ts
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export type TwoFactorMethod = 'authenticator' | 'email' | 'sms';

export interface TwoFactorStatusResponse {
  success: boolean;
  data: { enabled: boolean; method: TwoFactorMethod | null };
}

export interface SetupAuthenticatorResponse {
  success: boolean;
  data: { provisioning_uri: string; secret: string };
}

@Injectable({ providedIn: 'root' })
export class TwoFactorApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/2fa`;

  status(): Observable<TwoFactorStatusResponse> {
    return this.http.get<TwoFactorStatusResponse>(`${this.base}/status`);
  }

  setupAuthenticator(): Observable<SetupAuthenticatorResponse> {
    return this.http.post<SetupAuthenticatorResponse>(
      `${this.base}/setup-authenticator`, {},
    );
  }

  sendSetupOtp(method: 'email' | 'sms'): Observable<{ success: boolean; message: string }> {
    return this.http.post<{ success: boolean; message: string }>(
      `${this.base}/send-setup-otp`, { method },
    );
  }

  verifyAndEnable(method: TwoFactorMethod, code: string): Observable<{ success: boolean; message: string }> {
    return this.http.post<{ success: boolean; message: string }>(
      `${this.base}/verify-and-enable`, { method, code },
    );
  }

  disable(): Observable<{ success: boolean; message: string }> {
    // ActionTokenGuard handles the re-auth — the interceptor / page-level
    // ActionToken modal is responsible for capturing recent re-auth proof.
    return this.http.post<{ success: boolean; message: string }>(
      `${this.base}/disable`, {},
    );
  }
}
```

## `two-factor-tab.component.ts` — top-level state

```ts
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';

import { TwoFactorApiService, TwoFactorMethod } from '../services/two-factor-api.service';
import { TwoFactorEnrolModalComponent } from './two-factor-enrol-modal.component';
import { extractApiError } from '@core/services/api-error.util';

@Component({
  selector: 'app-settings-two-factor-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TwoFactorEnrolModalComponent],
  templateUrl: './two-factor-tab.component.html',
})
export class TwoFactorTabComponent {
  private readonly api = inject(TwoFactorApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly enabled = signal(false);
  protected readonly method = signal<TwoFactorMethod | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);

  /** Method the user is currently enrolling. Drives the modal. */
  protected readonly enrolling = signal<TwoFactorMethod | null>(null);

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.status()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.enabled.set(res.data?.enabled ?? false);
          this.method.set(res.data?.method ?? null);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load 2FA status.');
        },
      });
  }

  protected startEnrol(method: TwoFactorMethod): void {
    this.enrolling.set(method);
  }

  protected onEnrolComplete(): void {
    this.enrolling.set(null);
    this.reload();
  }

  protected onEnrolCancel(): void {
    this.enrolling.set(null);
  }

  protected disable(): void {
    this.api.disable()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.reload(),
        error: (err: HttpErrorResponse) =>
          this.error.set(extractApiError(err) ?? 'Could not disable 2FA.'),
      });
  }
}
```

## `two-factor-enrol-modal.component.ts` — TOTP / OTP capture

Handles the per-method enrol step. For TOTP it shows the QR code; for Email/SMS it triggers `send-setup-otp` and asks for the 6-digit code; all paths end with `verify-and-enable`.

QR rendering: reuse the existing dependency the legacy `accounts/two-factor/two-factor.component.ts` already pulls in (`qrcode` package — search for it in the legacy file). If it's not in `package.json`, render via a hosted `qrserver.com`-style fallback OR add `qrcode` as a dev-cheap dep.

```ts
@Component({
  selector: 'app-two-factor-enrol-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './two-factor-enrol-modal.component.html',
})
export class TwoFactorEnrolModalComponent {
  @Input({ required: true }) method!: TwoFactorMethod;
  @Output() complete = new EventEmitter<void>();
  @Output() cancel = new EventEmitter<void>();

  // ... per-method state: provisioning_uri (TOTP), otp_sent_at (Email/SMS),
  //     code form control, verify error, submitting flag.

  // On init:
  //   - method === 'authenticator' -> POST /2fa/setup-authenticator, render QR.
  //   - method !== 'authenticator' -> POST /2fa/send-setup-otp { method }.
  // On submit:
  //   - POST /2fa/verify-and-enable { method, code } -> emit complete.
}
```

## `two-factor-tab.component.html` — surface

```html
<div>
  @if (error(); as err) {
    <div class="mb-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
      {{ err }}
    </div>
  }

  @if (loading()) {
    <div class="rounded-lg border border-zinc-200 bg-white p-6 text-center text-sm text-zinc-500">
      Loading…
    </div>
  } @else {
    <div class="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm">
      <div class="flex items-center justify-between">
        <div>
          <div class="text-sm font-medium text-zinc-900">Two-factor authentication</div>
          <div class="text-xs text-zinc-500">
            @if (enabled()) {
              Currently <b class="text-emerald-700">ON</b> ({{ method() }}).
            } @else {
              Currently <b class="text-amber-700">OFF</b> — your account is protected by password only.
            }
          </div>
        </div>
        @if (enabled()) {
          <button class="rounded-md bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700" (click)="disable()">
            Disable
          </button>
        }
      </div>

      @if (!enabled()) {
        <div class="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
          <button class="rounded-md border border-zinc-300 p-3 text-left hover:bg-zinc-50" (click)="startEnrol('authenticator')">
            <div class="text-sm font-medium text-zinc-900">Authenticator app</div>
            <div class="text-xs text-zinc-500">Google Authenticator, Authy, 1Password</div>
          </button>
          <button class="rounded-md border border-zinc-300 p-3 text-left hover:bg-zinc-50" (click)="startEnrol('email')">
            <div class="text-sm font-medium text-zinc-900">Email OTP</div>
            <div class="text-xs text-zinc-500">6-digit code to your inbox</div>
          </button>
          <button class="rounded-md border border-zinc-300 p-3 text-left hover:bg-zinc-50" (click)="startEnrol('sms')">
            <div class="text-sm font-medium text-zinc-900">SMS OTP</div>
            <div class="text-xs text-zinc-500">6-digit code to your phone</div>
          </button>
        </div>
      }
    </div>
  }
</div>

@if (enrolling()) {
  <app-two-factor-enrol-modal
    [method]="enrolling()!"
    (complete)="onEnrolComplete()"
    (cancel)="onEnrolCancel()"
  />
}
```

## Disable + ActionTokenGuard

The legacy `/2fa/disable` route is decorated with `ActionTokenGuard()` — it requires a recent re-auth proof in the request. The accounts side already has an ActionToken capture modal (search for `ActionToken` in `features/accounts/`); the cleanest wire-up is to either:

(a) Reuse that modal here (preferred — keeps one source of truth for re-auth challenges), OR
(b) On a 401 from `/2fa/disable`, bounce to a small re-auth prompt and retry.

Option (a) keeps the codebase clean; the modal already understands the multi-method (password / TOTP / OTP) re-auth UX.

## Permission gate

None. 2FA self-service is personal security — every user must be able to enable + disable on their own account.

## Tests

Browser smoke:
1. Open Settings → Two-factor. Tab shows "Currently OFF" + three enrol options.
2. Click Authenticator → modal shows QR. Scan in Google Authenticator, type the 6-digit code, Submit → status flips to "ON (authenticator)."
3. Click Disable → ActionToken prompt → enter password → status flips back to "OFF."
4. Repeat for Email OTP and SMS OTP paths (skip SMS if no `TWILIO_*` env in dev).

## Acceptance

- Tab works for all three methods.
- Disable correctly requires re-auth via ActionToken.
- Status indicator + method shown accurately after each flip.

## Self-check vs the 10 rules

- ✅ Rule 5, 6 — no module / permission changes.
- ✅ Rule 8 — 7 files; under limit.
- ✅ Rule 10 — every enrol path is wired end-to-end; no half-shipped methods (Email-only or TOTP-only).

## Stop-and-report template

> ✅ Step 4 complete (track done).
> **Files changed:** 7 (5 new, 2 modified).
> **What you can verify:**
> 1. Settings → Two-factor shows current status + three enrol buttons.
> 2. Scan QR, enter code → 2FA flips ON.
> 3. Disable requires re-auth via ActionToken modal.
> **Tests added:** browser smoke only.
> **Self-check:** all 10 rules ✅.
> Track **settings-page** complete.

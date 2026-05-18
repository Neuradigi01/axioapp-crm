import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router } from '@angular/router';

import {
  StaffPickerUser,
  StaffPortalApiService,
} from '../staff-portal-api.service';
import { StaffSessionService } from '../staff-session.service';
import { initials } from '@core/services/text.util';

const DEFAULT_ORG_SLUG = 'demo';

/**
 * Staff-portal login. Two-step UX matching the master prompt:
 *
 *   1. Picker â€” pulls active staff for `org_slug` and shows colored
 *      avatar buttons.
 *   2. PIN â€” 4-digit keypad. Last 4 digits of the user's phone is
 *      the PIN. After 5 wrong attempts the server returns 429 and we
 *      surface the inline "Try again later" message.
 *
 * `org_slug` defaults to `demo`; can be overridden via `?org=<slug>`
 * so a single bundle can be branded per-store in later phases.
 */
@Component({
  selector: 'app-staff-portal-login',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  templateUrl: './login.page.html',
})
export class StaffPortalLoginPageComponent {
  protected readonly initials = initials;
  private readonly api = inject(StaffPortalApiService);
  private readonly session = inject(StaffSessionService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly orgSlug =
    this.route.snapshot.queryParamMap.get('org') || DEFAULT_ORG_SLUG;

  protected readonly users = signal<StaffPickerUser[]>([]);
  protected readonly loadingUsers = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly selectedUser = signal<StaffPickerUser | null>(null);
  protected readonly pin = signal<string>('');
  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  protected readonly digits = computed(() => this.pin().padEnd(4, ' '));

  protected readonly keypad: ReadonlyArray<string> = [
    '1', '2', '3', '4', '5', '6', '7', '8', '9', 'âŒ«', '0', 'OK',
  ];

  constructor() {
    this.loadUsers();
  }

  protected pickUser(u: StaffPickerUser): void {
    this.selectedUser.set(u);
    this.pin.set('');
    this.submitError.set(null);
  }

  protected backToPicker(): void {
    this.selectedUser.set(null);
    this.pin.set('');
    this.submitError.set(null);
  }

  protected pressKey(k: string): void {
    if (this.submitting()) return;
    if (k === 'âŒ«') {
      this.pin.update((p) => p.slice(0, -1));
      return;
    }
    if (k === 'OK') {
      this.submit();
      return;
    }
    if (this.pin().length >= 4) return;
    this.pin.update((p) => p + k);
    if (this.pin().length === 4) {
      // Auto-submit when the 4th digit lands.
      this.submit();
    }
  }

  protected avatarBg(id: string): string {
    const palette = [
      'bg-rose-100 text-rose-700',
      'bg-amber-100 text-amber-700',
      'bg-emerald-100 text-emerald-700',
      'bg-sky-100 text-sky-700',
      'bg-violet-100 text-violet-700',
      'bg-fuchsia-100 text-fuchsia-700',
    ];
    let h = 0;
    for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return palette[h % palette.length];
  }


  private loadUsers(): void {
    this.loadingUsers.set(true);
    this.loadError.set(null);
    this.api
      .listUsers(this.orgSlug)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.users.set(rows);
          this.loadingUsers.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.users.set([]);
          this.loadingUsers.set(false);
          this.loadError.set(
            this._extract(err) ?? 'Could not load staff list.',
          );
        },
      });
  }

  private submit(): void {
    const u = this.selectedUser();
    if (!u || this.pin().length !== 4 || this.submitting()) return;

    this.submitting.set(true);
    this.submitError.set(null);
    this.api
      .login(this.orgSlug, u.id, this.pin())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.session.save({ ...res, full_name: u.full_name });
          this.submitting.set(false);
          this.router.navigate(['/staff-portal/dashboard']);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.pin.set('');
          if (err.status === 429) {
            this.submitError.set(
              'Too many attempts. Try again in a minute.',
            );
          } else if (err.status === 401) {
            this.submitError.set('Wrong PIN. Try again.');
          } else {
            this.submitError.set(this._extract(err) ?? 'Login failed.');
          }
        },
      });
  }

  private _extract(err: HttpErrorResponse): string | null {
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const candidate =
        (body as { message?: string; detail?: unknown }).message
        ?? (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}

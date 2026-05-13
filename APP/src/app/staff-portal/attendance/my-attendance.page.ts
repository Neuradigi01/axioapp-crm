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

import {
  StaffAttendance,
  StaffPortalApiService,
} from '../staff-portal-api.service';

/**
 * My Attendance — month list of the signed-in staff's own clock-in/out
 * rows. The shell handles the actual clock-in/out button; here we just
 * read the history. Total hours shown at top so the user can see their
 * MTD time at a glance.
 */
@Component({
  selector: 'app-my-attendance-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  templateUrl: './my-attendance.page.html',
})
export class MyAttendancePageComponent {
  private readonly api = inject(StaffPortalApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly rows = signal<StaffAttendance[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly totalHours = computed(() => {
    let t = 0;
    for (const a of this.rows()) t += Number(a.hours ?? 0);
    return t.toFixed(2);
  });

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    const now = new Date();
    const first = new Date(now.getFullYear(), now.getMonth(), 1);
    const last = new Date(now.getFullYear(), now.getMonth() + 1, 0);
    this.api
      .attendance(this._iso(first), this._iso(last))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.rows.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.rows.set([]);
          this.loading.set(false);
          this.loadError.set(
            this._extract(err) ?? 'Could not load attendance.',
          );
        },
      });
  }

  protected formatTime(iso: string): string {
    return new Date(iso).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  protected formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString();
  }

  private _iso(d: Date): string {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
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

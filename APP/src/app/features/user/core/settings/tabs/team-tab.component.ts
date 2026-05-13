import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';

import { environment } from '../../../../../../environments/environment';

interface UserRow {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  role_id: string;
  role_name: string;
  is_active: boolean;
  created_at: string;
}

/**
 * Team tab — list the users in the org. Invite button is intentionally
 * a stub: the full invite flow ships in a later step (registration +
 * email + first-login set-password). For now the button surfaces the
 * "wired in a later step" copy so admins know it exists.
 */
@Component({
  selector: 'app-settings-team-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  templateUrl: './team-tab.component.html',
})
export class TeamTabComponent {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly base = `${environment.apiBaseUrl}/users`;

  protected readonly items = signal<UserRow[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.http
      .get<UserRow[]>(this.base)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.items.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loading.set(false);
          this.loadError.set(
            this._extract(err) ?? 'Could not load users.',
          );
        },
      });
  }

  protected initials(name: string): string {
    return name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((s) => s[0]?.toUpperCase() ?? '')
      .join('');
  }

  protected showInviteStub(): void {
    window.alert(
      'Invite flow ships in a future step. For now ask the org admin to add users directly via the API.',
    );
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

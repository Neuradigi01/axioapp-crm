import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DecimalPipe } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';

/**
 * tasks/automation-engine Step 14 — DKIM / SPF / DMARC status badge
 * panel. Lets the Owner verify that the sender domain they
 * connected to Mailgun / SendGrid / SES / Postmark is properly
 * authenticated before sending campaign volume through it.
 *
 * The check runs against the public DNS resolver via the backend
 * (which caches per-domain for 6 hours so the badge doesn't thrash
 * even with rapid re-views). Forcing a refresh re-runs the lookup
 * — useful right after updating DNS records.
 */
interface DomainStatus {
  domain: string;
  spf: 'valid' | 'invalid' | 'unknown';
  dkim: 'valid' | 'invalid' | 'unknown';
  dmarc: 'valid' | 'invalid' | 'unknown';
  last_checked_at: number;
}

@Component({
  selector: 'app-email-domain-status',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DecimalPipe, ReactiveFormsModule],
  templateUrl: './domain-status.component.html',
})
export class DomainStatusComponent {
  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly base = `${environment.apiBaseUrl}/email/domain-status`;

  protected readonly checking = signal(false);
  protected readonly result = signal<DomainStatus | null>(null);
  protected readonly error = signal<string | null>(null);

  protected readonly form = this.fb.group({
    domain: this.fb.control<string>('', { nonNullable: true }),
  });

  protected check(forceRefresh = false): void {
    const domain = (this.form.controls.domain.value || '').trim();
    if (!domain) return;
    this.checking.set(true);
    this.error.set(null);
    this._fetch(domain, forceRefresh)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.result.set(r);
          this.checking.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.checking.set(false);
          this.error.set(extractApiError(err) ?? 'Could not check domain.');
        },
      });
  }

  protected badgeClass(verdict: 'valid' | 'invalid' | 'unknown'): string {
    if (verdict === 'valid') {
      return 'bg-emerald-100 text-emerald-800 border-emerald-200';
    }
    if (verdict === 'invalid') {
      return 'bg-rose-100 text-rose-800 border-rose-200';
    }
    return 'bg-zinc-100 text-zinc-700 border-zinc-200';
  }

  private _fetch(domain: string, force: boolean): Observable<DomainStatus> {
    const params: Record<string, string> = { domain };
    if (force) params['force_refresh'] = 'true';
    return this.http.get<DomainStatus>(this.base, { params });
  }
}

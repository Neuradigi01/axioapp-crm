import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';

/**
 * tasks/automation-engine Step 13 — "Send rules" settings tab.
 *
 * Surfaces the three send-time compliance knobs the automation
 * dispatcher's send-guard layer reads before firing any
 * marketing-category run:
 *
 *   * Quiet hours (start + end + tz) — marketing runs inside the
 *     window are deferred to ``quiet_hours_end``, not dropped.
 *   * Frequency cap (per-week count + on/off toggle) — caps
 *     marketing sends per contact in any rolling 7-day window.
 *   * DPDP marketing-consent note — read-only reminder that
 *     opt-out contacts are skipped + opt-in is captured in the
 *     contact's profile (whatsapp_opt_in_status / email_opt_out).
 *
 * Transactional + service templates bypass all three controls;
 * the tab calls that out so operators don't expect (e.g.) order
 * receipts to honour the cap.
 */
interface SendRules {
  quiet_hours_start: string;
  quiet_hours_end: string;
  quiet_hours_timezone: string;
  marketing_frequency_cap_per_week: number;
  marketing_frequency_cap_enabled: boolean;
}

type SendRulesPatch = Partial<SendRules>;

@Component({
  selector: 'app-settings-automation-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './automation-settings-tab.component.html',
})
export class AutomationSettingsTabComponent {
  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly base = `${environment.apiBaseUrl}/tenants/send-rules`;

  protected readonly loading = signal(false);
  protected readonly saving = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saveError = signal<string | null>(null);
  protected readonly saveOk = signal(false);

  protected readonly form = this.fb.group({
    quiet_hours_start: this.fb.control<string>('21:00:00', {
      nonNullable: true,
    }),
    quiet_hours_end: this.fb.control<string>('09:00:00', {
      nonNullable: true,
    }),
    quiet_hours_timezone: this.fb.control<string>('Asia/Kolkata', {
      nonNullable: true,
    }),
    marketing_frequency_cap_per_week: this.fb.control<number>(3, {
      nonNullable: true,
    }),
    marketing_frequency_cap_enabled: this.fb.control<boolean>(true, {
      nonNullable: true,
    }),
  });

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.get()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this._hydrate(s);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load.');
        },
      });
  }

  protected save(): void {
    this.saving.set(true);
    this.saveError.set(null);
    this.saveOk.set(false);

    const dirty: SendRulesPatch = {};
    for (const [key, ctrl] of Object.entries(this.form.controls)) {
      if (ctrl.dirty) {
        (dirty as Record<string, unknown>)[key] = ctrl.value;
      }
    }
    if (Object.keys(dirty).length === 0) {
      this.saving.set(false);
      this.saveOk.set(true);
      return;
    }

    this.patch(dirty)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this._hydrate(s);
          this.saving.set(false);
          this.saveOk.set(true);
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.saveError.set(extractApiError(err) ?? 'Could not save.');
        },
      });
  }

  private _hydrate(s: SendRules): void {
    this.form.reset({
      quiet_hours_start: this._trimSeconds(s.quiet_hours_start),
      quiet_hours_end: this._trimSeconds(s.quiet_hours_end),
      quiet_hours_timezone: s.quiet_hours_timezone,
      marketing_frequency_cap_per_week: s.marketing_frequency_cap_per_week,
      marketing_frequency_cap_enabled: s.marketing_frequency_cap_enabled,
    });
  }

  /**
   * The backend returns ``HH:MM:SS``; the native ``<input type="time">``
   * accepts ``HH:MM`` so we trim before binding.
   */
  private _trimSeconds(t: string): string {
    if (!t) return t;
    const parts = t.split(':');
    return parts.length >= 2 ? `${parts[0]}:${parts[1]}` : t;
  }

  private get(): Observable<SendRules> {
    return this.http.get<SendRules>(this.base);
  }

  private patch(payload: SendRulesPatch): Observable<SendRules> {
    return this.http.patch<SendRules>(this.base, payload);
  }
}

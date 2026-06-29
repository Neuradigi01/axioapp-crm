import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { SettingsApiService } from '../settings-api.service';
import { extractApiError } from '@core/services/api-error.util';

/**
 * tasks/workflows Step 12 — Settings → General → Compliance.
 *
 * Surfaces the nine org-level compliance gates the workflow Send
 * actions check before shipping:
 *
 *   * Quiet hours window (start / end in the org timezone). When
 *     enabled, marketing sends inside the window are deferred to
 *     the end-time; transactional sends bypass per the bypass flag.
 *   * Per-week + per-day frequency caps for marketing sends. Set
 *     either to 0 to disable that side. Counts both workflow
 *     sends + campaign blasts toward the cap.
 *   * Unsubscribe-link enforcement for marketing emails — when
 *     enabled, the workflow auto-appends a standard footer if
 *     the rendered body doesn't already carry one.
 *
 * Read-mounts to ``GET /api/v1/settings``, writes via
 * ``PATCH /api/v1/settings`` — same surface as the rest of the
 * Settings → General page.
 */
@Component({
  selector: 'app-compliance-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './compliance-settings.component.html',
})
export class ComplianceSettingsComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(SettingsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly saved = signal(false);

  protected readonly form = this.fb.group({
    quiet_hours_enabled: this.fb.control<boolean>(true, { nonNullable: true }),
    quiet_hours_start: this.fb.control<string>('21:00', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    quiet_hours_end: this.fb.control<string>('09:00', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    quiet_hours_timezone: this.fb.control<string>('Asia/Kolkata', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    frequency_cap_marketing_per_week: this.fb.control<number>(5, {
      nonNullable: true,
      validators: [Validators.min(0), Validators.max(1000)],
    }),
    frequency_cap_marketing_per_day: this.fb.control<number>(2, {
      nonNullable: true,
      validators: [Validators.min(0), Validators.max(1000)],
    }),
    transactional_bypass_quiet_hours: this.fb.control<boolean>(true, {
      nonNullable: true,
    }),
    transactional_bypass_frequency_cap: this.fb.control<boolean>(true, {
      nonNullable: true,
    }),
    unsubscribe_link_required_in_marketing_email: this.fb.control<boolean>(
      true,
      { nonNullable: true },
    ),
  });

  ngOnInit(): void {
    this.load();
  }

  protected save(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.saving.set(true);
    this.saved.set(false);
    this.error.set(null);

    const payload = {
      ...this.form.getRawValue(),
      // The API expects ``HH:MM:SS`` for TIME columns; the form
      // input gives ``HH:MM`` — pad with ``:00`` so Pydantic
      // parses cleanly.
      quiet_hours_start: this._padSeconds(
        this.form.controls.quiet_hours_start.value,
      ),
      quiet_hours_end: this._padSeconds(
        this.form.controls.quiet_hours_end.value,
      ),
    };

    this.api
      .patch(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (settings) => {
          this.applyTo(settings);
          this.saving.set(false);
          this.saved.set(true);
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.error.set(extractApiError(err) ?? 'Could not save settings.');
        },
      });
  }

  private load(): void {
    this.loading.set(true);
    this.api
      .get()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (settings) => {
          this.applyTo(settings);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load settings.');
        },
      });
  }

  private applyTo(settings: {
    quiet_hours_enabled?: boolean;
    quiet_hours_start?: string;
    quiet_hours_end?: string;
    quiet_hours_timezone?: string;
    frequency_cap_marketing_per_week?: number;
    frequency_cap_marketing_per_day?: number;
    transactional_bypass_quiet_hours?: boolean;
    transactional_bypass_frequency_cap?: boolean;
    unsubscribe_link_required_in_marketing_email?: boolean;
  }): void {
    this.form.patchValue({
      quiet_hours_enabled: settings.quiet_hours_enabled ?? true,
      quiet_hours_start: this._stripSeconds(
        settings.quiet_hours_start ?? '21:00:00',
      ),
      quiet_hours_end: this._stripSeconds(
        settings.quiet_hours_end ?? '09:00:00',
      ),
      quiet_hours_timezone: settings.quiet_hours_timezone ?? 'Asia/Kolkata',
      frequency_cap_marketing_per_week:
        settings.frequency_cap_marketing_per_week ?? 5,
      frequency_cap_marketing_per_day:
        settings.frequency_cap_marketing_per_day ?? 2,
      transactional_bypass_quiet_hours:
        settings.transactional_bypass_quiet_hours ?? true,
      transactional_bypass_frequency_cap:
        settings.transactional_bypass_frequency_cap ?? true,
      unsubscribe_link_required_in_marketing_email:
        settings.unsubscribe_link_required_in_marketing_email ?? true,
    });
  }

  private _padSeconds(value: string): string {
    if (!value) return '00:00:00';
    return value.length === 5 ? `${value}:00` : value;
  }

  private _stripSeconds(value: string): string {
    return value.length >= 5 ? value.slice(0, 5) : value;
  }
}

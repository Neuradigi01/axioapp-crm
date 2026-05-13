import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import {
  OrgSettings,
  SettingsApiService,
} from '../settings-api.service';

/**
 * AI Settings tab — `ai_enabled` master switch + personality +
 * welcome message + reviews-auto-request toggle + delay hours.
 * Phase 5 reads these to wire the actual AI replies.
 */
@Component({
  selector: 'app-settings-ai-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './ai-settings-tab.component.html',
})
export class AiSettingsTabComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(SettingsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal(false);
  protected readonly saving = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saveError = signal<string | null>(null);
  protected readonly saveOk = signal(false);

  protected readonly form = this.fb.group({
    ai_enabled: this.fb.control<boolean>(false, { nonNullable: true }),
    ai_personality: this.fb.control<string | null>(null),
    ai_welcome_message: this.fb.control<string | null>(null),
    reviews_auto_request_enabled: this.fb.control<boolean>(false, {
      nonNullable: true,
    }),
    reviews_auto_request_delay_hours: this.fb.control<number>(24, {
      nonNullable: true,
    }),
  });

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .get()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this._hydrate(s);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(this._extract(err) ?? 'Could not load.');
        },
      });
  }

  protected save(): void {
    this.saving.set(true);
    this.saveError.set(null);
    this.saveOk.set(false);

    const dirty: Record<string, unknown> = {};
    for (const [key, ctrl] of Object.entries(this.form.controls)) {
      if (ctrl.dirty) dirty[key] = ctrl.value;
    }
    if (Object.keys(dirty).length === 0) {
      this.saving.set(false);
      this.saveOk.set(true);
      return;
    }

    this.api
      .patch(dirty)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this._hydrate(s);
          this.saving.set(false);
          this.saveOk.set(true);
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.saveError.set(this._extract(err) ?? 'Could not save.');
        },
      });
  }

  private _hydrate(s: OrgSettings): void {
    this.form.reset({
      ai_enabled: s.ai_enabled,
      ai_personality: s.ai_personality,
      ai_welcome_message: s.ai_welcome_message,
      reviews_auto_request_enabled: s.reviews_auto_request_enabled,
      reviews_auto_request_delay_hours: s.reviews_auto_request_delay_hours,
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

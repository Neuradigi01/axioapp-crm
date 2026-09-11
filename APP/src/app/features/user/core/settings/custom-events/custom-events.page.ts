import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { nullableTrim } from '@core/services/form.util';

import { CustomEvent, CustomEventsApiService } from './custom-events-api.service';

/**
 * `/user/settings/custom-events` — CRUD list for org-defined event
 * types. Admin defines events (e.g. `visa_expired`); staff fires them
 * from the contact detail page; workflows listening on
 * `custom.<event_key>` react (and typically fire a template).
 *
 * Inline add + inline edit — same pattern as catalog-categories to
 * keep the settings tabs consistent. `event_key` is only editable
 * during creation (immutable after — renames would silently break
 * every subscribed workflow).
 */
@Component({
  selector: 'app-custom-events-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule, RouterLink],
  templateUrl: './custom-events.page.html',
})
export class CustomEventsPageComponent {
  private readonly api = inject(CustomEventsApiService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly events = signal<CustomEvent[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saveError = signal<string | null>(null);
  protected readonly saving = signal(false);

  protected readonly addingOpen = signal(false);
  protected readonly editingId = signal<string | null>(null);

  protected readonly form = this.fb.group({
    event_key: this.fb.control('', {
      nonNullable: true,
      validators: [
        Validators.required,
        Validators.maxLength(64),
        Validators.pattern(/^[a-z][a-z0-9_]{0,63}$/),
      ],
    }),
    name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(128)],
    }),
    description: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.maxLength(2000)],
    }),
  });

  protected readonly totalEvents = computed(() => this.events().length);
  protected readonly totalFires = computed(() =>
    this.events().reduce((sum, e) => sum + e.fires_last_30d, 0),
  );

  constructor() {
    this.reload();
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.events.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(extractApiError(err) ?? 'Could not load custom events.');
          this.loading.set(false);
        },
      });
  }

  protected openAdd(): void {
    this.editingId.set(null);
    this.addingOpen.set(true);
    this.saveError.set(null);
    this.form.reset({ event_key: '', name: '', description: '' });
    this.form.controls.event_key.enable();
  }

  protected openEdit(evt: CustomEvent): void {
    this.addingOpen.set(false);
    this.editingId.set(evt.id);
    this.saveError.set(null);
    this.form.reset({
      event_key: evt.event_key,
      name: evt.name,
      description: evt.description ?? '',
    });
    // event_key is immutable after creation.
    this.form.controls.event_key.disable();
  }

  protected cancelForm(): void {
    this.addingOpen.set(false);
    this.editingId.set(null);
    this.saveError.set(null);
    this.form.controls.event_key.enable();
  }

  protected onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const raw = this.form.getRawValue();
    this.saving.set(true);
    this.saveError.set(null);

    const editingId = this.editingId();
    if (editingId) {
      this.api
        .update(editingId, {
          name: raw.name.trim(),
          description: nullableTrim(raw.description),
        })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: () => {
            this.saving.set(false);
            this.cancelForm();
            this.reload();
          },
          error: (err: HttpErrorResponse) => {
            this.saving.set(false);
            this.saveError.set(this.errorMessage(err));
          },
        });
    } else {
      this.api
        .create({
          event_key: raw.event_key.trim(),
          name: raw.name.trim(),
          description: nullableTrim(raw.description),
        })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: () => {
            this.saving.set(false);
            this.cancelForm();
            this.reload();
          },
          error: (err: HttpErrorResponse) => {
            this.saving.set(false);
            this.saveError.set(this.errorMessage(err));
          },
        });
    }
  }

  protected onDelete(evt: CustomEvent): void {
    const ok = window.confirm(
      `Delete custom event "${evt.name}"? Any workflows subscribed to ` +
        `custom.${evt.event_key} will stop firing. This cannot be undone.`,
    );
    if (!ok) return;
    const before = this.events();
    this.events.update((rows) => rows.filter((e) => e.id !== evt.id));
    this.api
      .delete(evt.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        error: (err: HttpErrorResponse) => {
          this.events.set(before);
          this.loadError.set(extractApiError(err) ?? 'Could not delete custom event.');
        },
      });
  }

  private errorMessage(err: HttpErrorResponse): string {
    if (err.status === 409) return 'A custom event with that key already exists.';
    if (err.status === 422) {
      return (
        extractApiError(err) ??
        'The event_key must be lowercase snake_case starting with a letter (e.g. visa_expired).'
      );
    }
    return extractApiError(err) ?? 'Could not save custom event.';
  }
}

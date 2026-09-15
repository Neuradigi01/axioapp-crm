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
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { nullableTrim } from '@core/services/form.util';

import {
  CustomEvent,
  CustomEventsApiService,
  DateFieldCatalogEntry,
  RecurringMode,
  ScheduleType,
} from './custom-events-api.service';

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
  imports: [ReactiveFormsModule, LucideAngularModule],
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
    schedule_type: this.fb.control<ScheduleType>('manual', { nonNullable: true }),
    // Composite value: `${source}::${field_ref}` so a single <select>
    // can group both source families under one option list.
    schedule_field: this.fb.control<string>('', { nonNullable: true }),
    schedule_offset_days: this.fb.control<number>(0, { nonNullable: true }),
    schedule_recurring: this.fb.control<RecurringMode>('none', { nonNullable: true }),
    schedule_hour_local: this.fb.control<number>(9, { nonNullable: true }),
  });

  /** Loaded lazily the first time the schedule_type toggles to
   *  'date_field' — no round-trip when the admin sticks to manual. */
  protected readonly dateFieldCatalog = signal<DateFieldCatalogEntry[] | null>(null);
  protected readonly catalogLoading = signal(false);
  protected readonly catalogError = signal<string | null>(null);

  /** Group the catalog by the label used in the <optgroup>. */
  protected readonly catalogGrouped = computed(() => {
    const rows = this.dateFieldCatalog() ?? [];
    const groups = new Map<string, DateFieldCatalogEntry[]>();
    for (const row of rows) {
      const bucket = groups.get(row.group) ?? [];
      bucket.push(row);
      groups.set(row.group, bucket);
    }
    return Array.from(groups.entries()).map(([label, options]) => ({ label, options }));
  });

  protected readonly HOURS_OF_DAY: ReadonlyArray<{ value: number; label: string }> = Array.from(
    { length: 24 },
    (_v, i) => ({
      value: i,
      label: `${String(i).padStart(2, '0')}:00`,
    }),
  );

  protected readonly OFFSET_OPTIONS: ReadonlyArray<{ value: number; label: string }> = [
    { value: -30, label: '30 days before' },
    { value: -14, label: '14 days before' },
    { value: -7, label: '7 days before' },
    { value: -3, label: '3 days before' },
    { value: -1, label: '1 day before' },
    { value: 0, label: 'On the day' },
    { value: 1, label: '1 day after' },
    { value: 3, label: '3 days after' },
    { value: 7, label: '7 days after' },
    { value: 14, label: '14 days after' },
    { value: 30, label: '30 days after' },
  ];

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
    this.form.reset({
      event_key: '',
      name: '',
      description: '',
      schedule_type: 'manual',
      schedule_field: '',
      schedule_offset_days: 0,
      schedule_recurring: 'none',
      schedule_hour_local: 9,
    });
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
      schedule_type: evt.schedule_type,
      schedule_field: evt.schedule ? `${evt.schedule.source}::${evt.schedule.field_ref}` : '',
      schedule_offset_days: evt.schedule?.offset_days ?? 0,
      schedule_recurring: evt.schedule?.recurring ?? 'none',
      schedule_hour_local: evt.schedule?.hour_local ?? 9,
    });
    // event_key is immutable after creation.
    this.form.controls.event_key.disable();
    if (evt.schedule_type === 'date_field') {
      this.ensureCatalogLoaded();
    }
  }

  protected onScheduleTypeChange(next: ScheduleType): void {
    this.form.controls.schedule_type.setValue(next);
    if (next === 'date_field') {
      this.ensureCatalogLoaded();
    }
  }

  private ensureCatalogLoaded(): void {
    if (this.dateFieldCatalog() !== null || this.catalogLoading()) return;
    this.catalogLoading.set(true);
    this.catalogError.set(null);
    this.api
      .listDateFieldCatalog()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.dateFieldCatalog.set(rows);
          this.catalogLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.catalogError.set(
            extractApiError(err) ?? 'Could not load date fields for scheduling.',
          );
          this.catalogLoading.set(false);
        },
      });
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

    // Schedule-specific guard: if the admin picked 'date_field' but
    // didn't select a field, block the submit with an inline error
    // rather than letting the API 422 out.
    if (raw.schedule_type === 'date_field' && !raw.schedule_field) {
      this.saveError.set('Pick a date field to watch — or switch back to manual.');
      return;
    }

    const schedulePayload =
      raw.schedule_type === 'date_field' ? this.buildSchedulePayload(raw.schedule_field) : null;

    this.saving.set(true);
    this.saveError.set(null);

    const editingId = this.editingId();
    if (editingId) {
      this.api
        .update(editingId, {
          name: raw.name.trim(),
          description: nullableTrim(raw.description),
          schedule_type: raw.schedule_type,
          schedule:
            raw.schedule_type === 'date_field'
              ? {
                  source: schedulePayload!.source,
                  field_ref: schedulePayload!.field_ref,
                  offset_days: raw.schedule_offset_days,
                  recurring: raw.schedule_recurring,
                  hour_local: raw.schedule_hour_local,
                }
              : null,
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
          schedule_type: raw.schedule_type,
          schedule:
            raw.schedule_type === 'date_field'
              ? {
                  source: schedulePayload!.source,
                  field_ref: schedulePayload!.field_ref,
                  offset_days: raw.schedule_offset_days,
                  recurring: raw.schedule_recurring,
                  hour_local: raw.schedule_hour_local,
                }
              : null,
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

  /** Parse the composite `${source}::${field_ref}` value coming out
   *  of the grouped <select>. */
  private buildSchedulePayload(composite: string): {
    source: 'system' | 'custom';
    field_ref: string;
  } {
    const [source, ...rest] = composite.split('::');
    return {
      source: source === 'custom' ? 'custom' : 'system',
      field_ref: rest.join('::'),
    };
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

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

import { ConfirmDialogService } from '../../shared/confirm-dialog/confirm-dialog.service';
import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../shared/forms/mobile-select.component';
import {
  CustomEvent,
  CustomEventsApiService,
  DateFieldCatalogEntry,
  EntityOption,
  EntityType,
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
  imports: [ReactiveFormsModule, LucideAngularModule, MobileSelectComponent],
  templateUrl: './custom-events.page.html',
})
export class CustomEventsPageComponent {
  private readonly api = inject(CustomEventsApiService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);
  private readonly confirmDialog = inject(ConfirmDialogService);

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
    entity_type: this.fb.control<EntityType>('contact', { nonNullable: true }),
    schedule_type: this.fb.control<ScheduleType>('manual', { nonNullable: true }),
    // Composite value: `${source}::${field_ref}` so a single dropdown
    // can group both source families under one option list.
    schedule_field: this.fb.control<string>('', { nonNullable: true }),
    // Offset + hour are stored as strings because the shared
    // `crm-mobile-select` CVA works with string values only; converted
    // to ints in `onSubmit` before shipping to the API.
    schedule_offset_days: this.fb.control<string>('0', { nonNullable: true }),
    schedule_recurring: this.fb.control<RecurringMode>('none', { nonNullable: true }),
    schedule_hour_local: this.fb.control<string>('9', { nonNullable: true }),
  });

  /** Loaded lazily the first time the schedule_type toggles to
   *  'date_field' — no round-trip when the admin sticks to manual.
   *  Re-fetched when the entity picker changes so the picker shows
   *  fields for the selected entity. */
  protected readonly dateFieldCatalog = signal<DateFieldCatalogEntry[] | null>(null);
  protected readonly catalogLoading = signal(false);
  protected readonly catalogError = signal<string | null>(null);
  protected readonly catalogEntity = signal<EntityType | null>(null);

  /** Loaded once on component init — the entity list is a static
   *  small list backend-side but sourcing it via API means future
   *  additions surface automatically. */
  protected readonly entityOptions = signal<ReadonlyArray<EntityOption>>([]);
  protected readonly entitySelectOptions = computed<ReadonlyArray<MobileSelectOption>>(() =>
    this.entityOptions().map((e) => ({ value: e.key, label: e.label })),
  );

  /** Grouped options for the `crm-mobile-select` field picker. Each
   *  option's `value` is the composite `${source}::${field_ref}` the
   *  submit handler decodes; `group` drives the section headers. */
  protected readonly fieldOptions = computed<ReadonlyArray<MobileSelectOption>>(() => {
    const rows = this.dateFieldCatalog() ?? [];
    // Keep the server-side ordering (system group first, then custom)
    // so section headers stay in the intended order.
    return rows.map((row) => ({
      value: `${row.source}::${row.field_ref}`,
      label: row.label,
      group: row.group,
    }));
  });

  /** Offset dropdown options — same values as before, now flowing
   *  through `crm-mobile-select`. String-encoded because the shared
   *  component takes `string` values (Angular Forms coerces). */
  protected readonly offsetOptions: ReadonlyArray<MobileSelectOption> = [
    { value: '-30', label: '30 days before' },
    { value: '-14', label: '14 days before' },
    { value: '-7', label: '7 days before' },
    { value: '-3', label: '3 days before' },
    { value: '-1', label: '1 day before' },
    { value: '0', label: 'On the day' },
    { value: '1', label: '1 day after' },
    { value: '3', label: '3 days after' },
    { value: '7', label: '7 days after' },
    { value: '14', label: '14 days after' },
    { value: '30', label: '30 days after' },
  ];

  /** 24-hour options. */
  protected readonly hourOptions: ReadonlyArray<MobileSelectOption> = Array.from(
    { length: 24 },
    (_v, i) => ({
      value: String(i),
      label: `${String(i).padStart(2, '0')}:00`,
    }),
  );

  protected readonly totalEvents = computed(() => this.events().length);
  protected readonly totalFires = computed(() =>
    this.events().reduce((sum, e) => sum + e.fires_last_30d, 0),
  );

  constructor() {
    this.reload();
    // Fire once at init; the response is small and always cached
    // client-side after the first call.
    this.api
      .listEntities()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.entityOptions.set(rows),
        error: () => {
          // Fall back to a hardcoded default so the modal still opens
          // when the endpoint is unreachable (rare — same backend, same
          // auth as list()).
          this.entityOptions.set([
            { key: 'contact', label: 'Contact' },
            { key: 'lead', label: 'Lead' },
            { key: 'appointment', label: 'Appointment' },
          ]);
        },
      });
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
      entity_type: 'contact',
      schedule_type: 'manual',
      schedule_field: '',
      schedule_offset_days: '0',
      schedule_recurring: 'none',
      schedule_hour_local: '9',
    });
    this.form.controls.event_key.enable();
    this.form.controls.entity_type.enable();
  }

  protected openEdit(evt: CustomEvent): void {
    this.addingOpen.set(false);
    this.editingId.set(evt.id);
    this.saveError.set(null);
    this.form.reset({
      event_key: evt.event_key,
      name: evt.name,
      description: evt.description ?? '',
      entity_type: evt.entity_type,
      schedule_type: evt.schedule_type,
      schedule_field: evt.schedule ? `${evt.schedule.source}::${evt.schedule.field_ref}` : '',
      schedule_offset_days: String(evt.schedule?.offset_days ?? 0),
      schedule_recurring: evt.schedule?.recurring ?? 'none',
      schedule_hour_local: String(evt.schedule?.hour_local ?? 9),
    });
    // event_key + entity_type are immutable after creation.
    this.form.controls.event_key.disable();
    this.form.controls.entity_type.disable();
    if (evt.schedule_type === 'date_field') {
      this.reloadCatalog(evt.entity_type);
    }
  }

  protected onScheduleTypeChange(next: ScheduleType): void {
    this.form.controls.schedule_type.setValue(next);
    if (next === 'date_field') {
      this.reloadCatalog(this.form.controls.entity_type.value);
    }
  }

  /** Called from the entity picker's (valueChange) — the picker
   *  writes the form control, we invalidate the field selection
   *  (since fields on Lead are different from Contact) and re-fetch
   *  the catalog. */
  protected onEntityChange(next: EntityType): void {
    if (this.form.controls.entity_type.disabled) return;
    // `formControlName` on the crm-mobile-select already wrote the
    // value via ControlValueAccessor — we only side-effect here.
    // Clear the field pick — a field valid for Contact is not valid
    // for Lead so we must force a re-selection.
    this.form.controls.schedule_field.setValue('');
    // Manual firing only exists for contact-scoped events. Auto-flip
    // to date_field when the user switches to Lead / Appointment so
    // the form doesn't sit in an invalid state.
    if (next !== 'contact' && this.form.controls.schedule_type.value === 'manual') {
      this.form.controls.schedule_type.setValue('date_field');
    }
    if (this.form.controls.schedule_type.value === 'date_field') {
      this.reloadCatalog(next);
    }
  }

  /** Load (or reload) the date-field catalog for the given entity.
   *  Idempotent when the requested entity already matches what's in
   *  the signal — that skips redundant round-trips when the user
   *  toggles manual↔date_field on the same entity. */
  private reloadCatalog(entity: EntityType): void {
    if (this.catalogEntity() === entity && this.dateFieldCatalog() !== null) return;
    if (this.catalogLoading()) return;
    this.catalogLoading.set(true);
    this.catalogError.set(null);
    this.catalogEntity.set(entity);
    this.api
      .listDateFieldCatalog(entity)
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
      raw.schedule_type === 'date_field'
        ? {
            ...this.buildSchedulePayload(raw.schedule_field),
            offset_days: Number(raw.schedule_offset_days),
            recurring: raw.schedule_recurring,
            hour_local: Number(raw.schedule_hour_local),
          }
        : null;

    this.saving.set(true);
    this.saveError.set(null);

    const editingId = this.editingId();
    if (editingId) {
      this.api
        .update(editingId, {
          name: raw.name.trim(),
          description: nullableTrim(raw.description),
          schedule_type: raw.schedule_type,
          schedule: schedulePayload,
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
          entity_type: raw.entity_type,
          schedule_type: raw.schedule_type,
          schedule: schedulePayload,
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

  protected async onDelete(evt: CustomEvent): Promise<void> {
    const ok = await this.confirmDialog.ask({
      title: `Delete "${evt.name}"?`,
      body:
        `Any workflows subscribed to custom.${evt.event_key} will stop firing. ` +
        `Occurrence history is retained but no new events will publish. This cannot be undone.`,
      confirmLabel: 'Delete event',
      cancelLabel: 'Keep it',
      danger: true,
    });
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

import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  OnInit,
  Output,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, ValidatorFn, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { Subject, of } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';
import { extractApiError } from '@core/services/api-error.util';
import { nullableTrim } from '@core/services/form.util';

import { ContactListItem, ContactsApiService } from '../../../core/contacts/contacts-api.service';
import { StaffApiService, StaffListItem } from '../../../core/staff/staff-api.service';
import { StandardFieldsApiService } from '../../../core/standard-fields/standard-fields-api.service';
import { StandardFieldsSignalsService } from '../../../core/standard-fields/standard-fields-signals.service';
import type { StandardFieldRendered } from '../../../core/standard-fields/types';
import { CustomOrder, CustomOrdersApiService } from '../custom-orders/custom-orders-api.service';
import { FieldOpsApiService, FieldVisitPurpose } from './field-ops-api.service';

/**
 * Schedule a new on-site visit. Composes an `AppointmentCreate` body
 * (contact + assignee + scheduled_at + duration) with the pack-specific
 * `purpose` + optional `custom_order_id`. The backend creates the
 * appointment and the field-visit in one transaction (rule-1 friendly:
 * the pack reuses the core appointments engine).
 */
@Component({
  selector: 'app-schedule-visit-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule],
  templateUrl: './schedule-visit-modal.component.html',
})
export class ScheduleVisitModalComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(FieldOpsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly staffApi = inject(StaffApiService);
  private readonly customOrdersApi = inject(CustomOrdersApiService);
  private readonly stdApi = inject(StandardFieldsApiService);
  private readonly stdSignals = inject(StandardFieldsSignalsService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly stdFields = signal<Record<string, StandardFieldRendered>>({});

  protected stdField(key: string): StandardFieldRendered | undefined {
    return this.stdFields()[key];
  }

  protected isHidden(key: string): boolean {
    return this.stdField(key)?.is_hidden === true;
  }

  constructor() {
    effect(() => {
      this.stdSignals.changedAt();
      this.refreshStdFields();
    });
  }

  private refreshStdFields(): void {
    this.stdApi.render('field_visit').subscribe({
      next: (resp) => {
        const map: Record<string, StandardFieldRendered> = {};
        for (const f of resp.items) map[f.field_key] = f;
        this.stdFields.set(map);
        this.applyStandardValidators(map);
      },
      error: () => {
        /* fallbacks keep the form usable */
      },
    });
  }

  /** title/scheduled_date/scheduled_time/duration_min/assigned_to_id are
   *  backend-locked-required. duration_min accepts min/max overrides. */
  private applyStandardValidators(map: Record<string, StandardFieldRendered>): void {
    this.form.controls.title.setValidators([Validators.required, Validators.maxLength(255)]);
    this.form.controls.title.updateValueAndValidity({ emitEvent: false });

    this.form.controls.scheduled_date.setValidators([Validators.required]);
    this.form.controls.scheduled_date.updateValueAndValidity({
      emitEvent: false,
    });

    this.form.controls.scheduled_time.setValidators([Validators.required]);
    this.form.controls.scheduled_time.updateValueAndValidity({
      emitEvent: false,
    });

    const durRow = map['duration_min'];
    const durV: ValidatorFn[] = [
      Validators.required,
      Validators.min(durRow?.min_value ?? 15),
      Validators.max(durRow?.max_value ?? 1440),
    ];
    this.form.controls.duration_min.setValidators(durV);
    this.form.controls.duration_min.updateValueAndValidity({
      emitEvent: false,
    });

    this.form.controls.assigned_to_id.setValidators([Validators.required]);
    this.form.controls.assigned_to_id.updateValueAndValidity({
      emitEvent: false,
    });

    const setReq = (
      ctrl: 'purpose' | 'location' | 'notes',
      row: StandardFieldRendered | undefined,
    ): void => {
      const v: ValidatorFn[] = [];
      if (row?.is_required) v.push(Validators.required);
      this.form.controls[ctrl].setValidators(v);
      this.form.controls[ctrl].updateValueAndValidity({ emitEvent: false });
    };
    setReq('purpose', map['purpose']);
    setReq('location', map['location']);
    setReq('notes', map['notes']);
  }

  @Input() set submitting(value: boolean) {
    this._submitting.set(value);
  }

  @Output() readonly created = new EventEmitter<void>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly _submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  protected readonly staff = signal<StaffListItem[]>([]);
  protected readonly recentOrders = signal<CustomOrder[]>([]);

  // Contact picker state â€” same pattern as the custom-order modal.
  protected readonly selectedContact = signal<ContactListItem | null>(null);
  protected readonly contactQuery = signal('');
  protected readonly contactResults = signal<ContactListItem[]>([]);
  protected readonly contactSearchOpen = signal(false);
  private readonly contactQuery$ = new Subject<string>();

  readonly form = this.fb.group({
    title: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    purpose: this.fb.control<FieldVisitPurpose>('measurement', {
      nonNullable: true,
    }),
    scheduled_date: this.fb.control<string>(this.todayIso(), {
      nonNullable: true,
      validators: [Validators.required],
    }),
    scheduled_time: this.fb.control<string>('10:00', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    duration_min: this.fb.control<number>(60, {
      nonNullable: true,
      validators: [Validators.required, Validators.min(15)],
    }),
    location: this.fb.control<string>('', { nonNullable: true }),
    assigned_to_id: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    custom_order_id: this.fb.control<string>('', { nonNullable: true }),
    notes: this.fb.control<string>('', { nonNullable: true }),
  });

  protected readonly canSubmit = computed(() => this.form.valid && this.selectedContact() !== null);

  ngOnInit(): void {
    // Staff list for the assignee picker.
    this.staffApi
      .list()
      .pipe(
        catchError(() => of<StaffListItem[]>([])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((rows) => {
        const active = rows.filter((r) => r.is_active);
        this.staff.set(active);
        // Default to first active user if nothing selected yet.
        if (!this.form.controls.assigned_to_id.value && active.length > 0) {
          this.form.controls.assigned_to_id.setValue(active[0].id);
        }
      });

    // Recent open custom orders so the user can link this visit to one.
    this.customOrdersApi
      .list({ size: 25 })
      .pipe(
        catchError(() => of({ items: [] as CustomOrder[], total: 0, page: 1, size: 25 })),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((resp) => this.recentOrders.set(resp.items));

    // Debounced contact search.
    this.contactQuery$
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        switchMap((q) =>
          this.contactsApi
            .list({ q: q || undefined, size: 8 })
            .pipe(
              catchError(() => of({ items: [] as ContactListItem[], total: 0, page: 1, size: 8 })),
            ),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((resp) => this.contactResults.set(resp.items));

    // Preload the first page so the dropdown opens instantly on focus.
    this.contactQuery$.next('');
  }

  protected onContactQueryInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.contactQuery.set(value);
    this.contactSearchOpen.set(true);
    this.contactQuery$.next(value);
  }

  protected onContactFocus(): void {
    this.contactSearchOpen.set(true);
    if (this.contactResults().length === 0) {
      this.contactQuery$.next(this.contactQuery());
    }
  }

  protected onContactBlur(): void {
    setTimeout(() => this.contactSearchOpen.set(false), 150);
  }

  protected selectContact(c: ContactListItem): void {
    this.selectedContact.set(c);
    this.contactSearchOpen.set(false);
    this.contactQuery.set('');
    this.contactResults.set([]);
  }

  protected clearContact(): void {
    this.selectedContact.set(null);
    this.contactQuery.set('');
    this.contactSearchOpen.set(true);
  }

  protected submit(): void {
    if (!this.canSubmit() || this._submitting()) return;
    const contact = this.selectedContact();
    if (!contact) {
      this.submitError.set('Please pick a contact.');
      return;
    }
    this._submitting.set(true);
    this.submitError.set(null);

    const v = this.form.getRawValue();
    const scheduledAt = this.combineDateTime(v.scheduled_date, v.scheduled_time);

    this.api
      .create({
        appointment: {
          contact_id: contact.id,
          title: v.title.trim(),
          purpose: v.purpose,
          scheduled_at: scheduledAt,
          duration_min: v.duration_min,
          location: nullableTrim(v.location),
          assigned_to_id: v.assigned_to_id,
          custom_data: {},
        },
        purpose: v.purpose,
        custom_order_id: v.custom_order_id.trim() || null,
        notes: nullableTrim(v.notes),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this._submitting.set(false);
          this.created.emit();
        },
        error: (err: HttpErrorResponse) => {
          this._submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Could not schedule the visit.');
        },
      });
  }

  private todayIso(): string {
    const d = new Date();
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  }

  private combineDateTime(date: string, time: string): string {
    // Build a local-time ISO string with explicit TZ offset so the
    // backend receives the user's intended local moment.
    const [y, m, d] = date.split('-').map((n) => parseInt(n, 10));
    const [hh, mm] = time.split(':').map((n) => parseInt(n, 10));
    const dt = new Date(y, (m ?? 1) - 1, d ?? 1, hh ?? 0, mm ?? 0, 0);
    return dt.toISOString();
  }
}

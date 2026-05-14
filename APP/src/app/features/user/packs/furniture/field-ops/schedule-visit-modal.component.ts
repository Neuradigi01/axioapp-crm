import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  OnInit,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  FormBuilder,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { Subject, of } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import {
  ContactListItem,
  ContactsApiService,
} from '../../../core/contacts/contacts-api.service';
import {
  StaffApiService,
  StaffListItem,
} from '../../../core/staff/staff-api.service';
import {
  CustomOrder,
  CustomOrdersApiService,
} from '../custom-orders/custom-orders-api.service';
import {
  FieldOpsApiService,
  FieldVisitPurpose,
} from './field-ops-api.service';

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
  private readonly destroyRef = inject(DestroyRef);

  @Input() set submitting(value: boolean) {
    this._submitting.set(value);
  }

  @Output() readonly created = new EventEmitter<void>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly _submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  protected readonly staff = signal<StaffListItem[]>([]);
  protected readonly recentOrders = signal<CustomOrder[]>([]);

  // Contact picker state — same pattern as the custom-order modal.
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

  protected readonly canSubmit = computed(
    () => this.form.valid && this.selectedContact() !== null,
  );

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
        catchError(() =>
          of({ items: [] as CustomOrder[], total: 0, page: 1, size: 25 }),
        ),
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
              catchError(() =>
                of({ items: [] as ContactListItem[], total: 0, page: 1, size: 8 }),
              ),
            ),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((resp) => this.contactResults.set(resp.items));
  }

  protected onContactQueryInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.contactQuery.set(value);
    this.contactSearchOpen.set(true);
    this.contactQuery$.next(value);
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
          location: this.nullableTrim(v.location),
          assigned_to_id: v.assigned_to_id,
          custom_data: {},
        },
        purpose: v.purpose,
        custom_order_id: v.custom_order_id.trim() || null,
        notes: this.nullableTrim(v.notes),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this._submitting.set(false);
          this.created.emit();
        },
        error: (err: HttpErrorResponse) => {
          this._submitting.set(false);
          this.submitError.set(
            this.extractError(err) ?? 'Could not schedule the visit.',
          );
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

  private nullableTrim(v: string | null | undefined): string | null {
    if (v === null || v === undefined) return null;
    const t = v.trim();
    return t.length === 0 ? null : t;
  }

  private extractError(err: HttpErrorResponse): string | null {
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

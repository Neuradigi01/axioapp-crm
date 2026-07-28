import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { environment } from '../../../../../environments/environment';

import { FurnitureAuthService, MeResponse } from '../auth/auth.service';
import { extractApiError } from '@core/services/api-error.util';
import { ContactListItem, ContactsApiService } from '../contacts/contacts-api.service';
import { BaseFormModalComponent } from '../shared/components/base-form-modal.component';
import { FieldDef } from '../shared/dynamic-form/types';
import type { StandardFieldRendered } from '../standard-fields/types';
import { commonValidators, withRequiredIf } from '../shared/validators';
import {
  Appointment,
  AppointmentCreate,
  AppointmentsApiService,
  ConflictBody,
} from './appointments-api.service';

/**
 * Modal that books a new appointment.
 *
 * Three sections:
 *   - Contact picker (debounced search via contacts API).
 *   - Standard fields (title, purpose, scheduled_at, duration_min,
 *     location, **assignee**). The Assignee dropdown lists every
 *     active org user (`GET /api/v1/users`) and defaults to the
 *     current user — solo users see no extra friction; Owner/Admin
 *     can pick another staff member to delegate.
 *   - Conflict banner — when the create call returns 409 with a
 *     `conflicts: [...]` array we surface the conflicting appointment
 *     ids and let the parent map them to titles via `conflictTitleFor`.
 *
 * `defaultDate` lets the parent pre-fill the scheduled_at from the
 * currently-selected day on the calendar.
 */
interface OrgUser {
  id: string;
  full_name: string;
  is_active: boolean;
}
@Component({
  selector: 'app-book-appointment-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './book-appointment-modal.component.html',
})
export class BookAppointmentModalComponent extends BaseFormModalComponent {
  protected readonly entityType = 'appointment';

  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);
  private readonly api = inject(AppointmentsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly auth = inject(FurnitureAuthService);

  protected renderCustomFields$(): Observable<FieldDef[]> {
    return this.api.renderFields();
  }

  /** `title` + `scheduled_at` + `duration_min` are backend-required (locked).
   *  `purpose` / `location` accept the `required` override.
   *  `duration_min` additionally accepts `min`/`max` (default 1–1440). */
  protected applyStandardValidators(map: Record<string, StandardFieldRendered>): void {
    this.form.controls.title.setValidators([
      commonValidators.required,
      commonValidators.maxLength(255),
    ]);
    this.form.controls.title.updateValueAndValidity({ emitEvent: false });
    // scheduled_at must be forward-looking (bookings can't land in the past).
    this.form.controls.scheduled_at.setValidators([
      commonValidators.required,
      commonValidators.dateNotPast,
    ]);
    this.form.controls.scheduled_at.updateValueAndValidity({ emitEvent: false });

    const durRow = map['duration_min'];
    // Floor/ceiling always apply (1 min – 24 hr); override tightens further.
    this.form.controls.duration_min.setValidators([
      commonValidators.required,
      Validators.min(Math.max(1, durRow?.min_value ?? 1)),
      Validators.max(Math.min(1440, durRow?.max_value ?? 1440)),
    ]);
    this.form.controls.duration_min.updateValueAndValidity({ emitEvent: false });

    const setReq = (ctrl: 'purpose' | 'location', row: StandardFieldRendered | undefined): void => {
      this.form.controls[ctrl].setValidators(
        withRequiredIf([commonValidators.maxLength(1000)], row),
      );
      this.form.controls[ctrl].updateValueAndValidity({ emitEvent: false });
    };
    setReq('purpose', map['purpose']);
    setReq('location', map['location']);
  }

  /** Pre-fill the date side of `scheduled_at`. Time defaults to 10:00. */
  @Input() set defaultDate(value: Date | null) {
    if (value && !this.scheduledAtControl.value) {
      this.scheduledAtControl.setValue(this.toDatetimeLocalString(value, 10));
    }
  }

  /** W5 — pre-select a contact when the modal is opened via a deep-link
   *  from another page (e.g. the walk-ins page "Schedule" row action).
   *  The setter fills the `selectedContact` signal so the contact
   *  picker renders in "chosen" mode from the first paint. */
  @Input() set prefillContact(value: ContactListItem | null) {
    if (value && !this.selectedContact()) {
      this.selectedContact.set(value);
    }
  }

  /** Map a conflicting appointment id → human-readable label (set by parent). */
  @Input() conflictTitleFor: (id: string) => string | null = () => null;

  @Output() readonly created = new EventEmitter<Appointment>();

  protected readonly me = signal<MeResponse | null>(null);
  protected readonly conflicts = signal<string[]>([]);

  protected readonly selectedContact = signal<ContactListItem | null>(null);
  protected readonly contactQuery = signal('');
  protected readonly contactResults = signal<ContactListItem[]>([]);
  protected readonly contactSearchOpen = signal(false);

  /** Active org users for the Assignee dropdown. Loaded once on
   * ngOnInit via `GET /api/v1/users`; inactive users filtered out
   * client-side. Empty until the request lands. */
  protected readonly users = signal<OrgUser[]>([]);

  private readonly contactQuery$ = new Subject<string>();

  protected readonly scheduledAtControl = this.fb.control('', {
    nonNullable: true,
    validators: [commonValidators.required, commonValidators.dateNotPast],
  });

  /** Assigned user id. Initialised to the current user's id once
   * `/users/me` lands, so solo users see no extra friction. Owner /
   * Admin override by picking another option in the dropdown. */
  protected readonly assigneeControl = this.fb.control('', {
    nonNullable: true,
    validators: [commonValidators.required],
  });

  protected readonly form = this.fb.group({
    title: this.fb.control('', {
      nonNullable: true,
      validators: [commonValidators.required, commonValidators.maxLength(255)],
    }),
    purpose: this.fb.control('', {
      nonNullable: true,
      validators: [commonValidators.maxLength(1000)],
    }),
    scheduled_at: this.scheduledAtControl,
    duration_min: this.fb.control<number>(60, {
      nonNullable: true,
      validators: [commonValidators.required, Validators.min(1), Validators.max(24 * 60)],
    }),
    location: this.fb.control('', {
      nonNullable: true,
      validators: [commonValidators.maxLength(1000)],
    }),
    assigned_to_id: this.assigneeControl,
  });

  readonly canSubmit = computed(() => this.me() !== null && !this.submitting$());

  override ngOnInit(): void {
    super.ngOnInit();

    this.auth
      .me()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (me) => {
          this.me.set(me);
          // Default the assignee to the current user once we know who
          // they are. Owner can override by picking another option.
          if (!this.assigneeControl.value) {
            this.assigneeControl.setValue(me.id);
          }
        },
        error: () => this.me.set(null),
      });

    // Load active org users for the Assignee dropdown. A `/users`
    // failure must NOT block booking — fall back to a one-row list
    // containing just the current user (which `me()` will populate
    // above) so the modal remains submittable.
    this.http
      .get<OrgUser[]>(`${environment.apiBaseUrl}/users`)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (list) => {
          this.users.set(list.filter((u) => u.is_active));
        },
        error: () => this.users.set([]),
      });

    this.contactQuery$
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        switchMap((q) => this.contactsApi.list({ q: q || undefined, size: 8 })),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => this.contactResults.set(resp.items),
        error: () => this.contactResults.set([]),
      });

    // Preload the first page of contacts so the dropdown is instant
    // the moment the search field gets focus.
    this.contactQuery$.next('');
  }

  protected onContactQueryInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.contactQuery.set(value);
    this.contactSearchOpen.set(true);
    this.contactQuery$.next(value);
  }

  /** Open the dropdown on focus so the operator sees the top contacts
   *  without having to type — mirrors how HubSpot / Pipedrive behave. */
  protected onContactFocus(): void {
    this.contactSearchOpen.set(true);
    if (this.contactResults().length === 0) {
      this.contactQuery$.next(this.contactQuery());
    }
  }

  /** Close the dropdown when the field loses focus. Delayed so a click
   *  on a suggestion still fires before the list is removed from the
   *  DOM. */
  protected onContactBlur(): void {
    setTimeout(() => this.contactSearchOpen.set(false), 150);
  }

  protected selectContact(c: ContactListItem): void {
    this.selectedContact.set(c);
    this.contactSearchOpen.set(false);
    this.contactQuery.set('');
    this.contactResults.set([]);
    this._submitError.set(null);
  }

  protected clearContact(): void {
    this.selectedContact.set(null);
    this.contactQuery.set('');
    this.contactResults.set([]);
    this.contactSearchOpen.set(true);
  }

  protected onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const contact = this.selectedContact();
    if (!contact) {
      this._submitError.set('Please pick a contact.');
      return;
    }
    const user = this.me();
    if (!user) {
      this._submitError.set('Could not resolve the current user.');
      return;
    }
    this._submitError.set(null);
    this.conflicts.set([]);
    this._submitting.set(true);

    const raw = this.form.getRawValue();
    const payload: AppointmentCreate = {
      contact_id: contact.id,
      title: raw.title.trim(),
      purpose: raw.purpose.trim() || null,
      scheduled_at: this.toIsoFromLocal(raw.scheduled_at),
      duration_min: Number(raw.duration_min),
      location: raw.location.trim() || null,
      // Picked from the Assignee dropdown; falls back to the current
      // user when the dropdown is empty (e.g. `/users` failed and the
      // user just submits the form with the form's default).
      assigned_to_id: (raw.assigned_to_id || '').trim() || user.id,
    };

    this.api
      .create(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (appt) => {
          this._submitting.set(false);
          this.created.emit(appt);
        },
        error: (err: HttpErrorResponse) => {
          this._submitting.set(false);
          if (err.status === 409) {
            const body = err.error as Partial<ConflictBody>;
            this.conflicts.set(body?.conflicts ?? []);
            this._submitError.set(body?.message ?? 'Time conflict: this slot is already booked.');
          } else {
            this._submitError.set(extractApiError(err) ?? 'Could not create appointment.');
          }
        },
      });
  }

  protected conflictLabel(id: string): string {
    return this.conflictTitleFor(id) ?? id.slice(0, 8) + '…';
  }

  /** Convert `<input type="datetime-local">` value → backend ISO. */
  private toIsoFromLocal(value: string): string {
    const d = new Date(value);
    return d.toISOString();
  }

  /** Convert a Date → "YYYY-MM-DDTHH:mm" for <input type="datetime-local">. */
  private toDatetimeLocalString(d: Date, hour: number): string {
    const local = new Date(d.getFullYear(), d.getMonth(), d.getDate(), hour, 0, 0, 0);
    const pad = (n: number) => String(n).padStart(2, '0');
    return (
      `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())}` +
      `T${pad(local.getHours())}:${pad(local.getMinutes())}`
    );
  }
}

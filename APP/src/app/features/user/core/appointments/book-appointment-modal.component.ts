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
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { FurnitureAuthService, MeResponse } from '../auth/auth.service';
import { extractApiError } from '@core/services/api-error.util';
import {
  ContactListItem,
  ContactsApiService,
} from '../contacts/contacts-api.service';
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
 *     location). `assigned_to_id` defaults to the current user; there's
 *     no users-list API yet so we keep it implicit.
 *   - Conflict banner â€” when the create call returns 409 with a
 *     `conflicts: [...]` array we surface the conflicting appointment
 *     ids and let the parent map them to titles via `conflictTitleFor`.
 *
 * `defaultDate` lets the parent pre-fill the scheduled_at from the
 * currently-selected day on the calendar.
 */
@Component({
  selector: 'app-book-appointment-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './book-appointment-modal.component.html',
})
export class BookAppointmentModalComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(AppointmentsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  /** Pre-fill the date side of `scheduled_at`. Time defaults to 10:00. */
  @Input() set defaultDate(value: Date | null) {
    if (value && !this.scheduledAtControl.value) {
      this.scheduledAtControl.setValue(this.toDatetimeLocalString(value, 10));
    }
  }

  /** Map a conflicting appointment id â†’ human-readable label (set by parent). */
  @Input() conflictTitleFor: (id: string) => string | null = () => null;

  @Output() readonly created = new EventEmitter<Appointment>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly me = signal<MeResponse | null>(null);
  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);
  protected readonly conflicts = signal<string[]>([]);

  protected readonly selectedContact = signal<ContactListItem | null>(null);
  protected readonly contactQuery = signal('');
  protected readonly contactResults = signal<ContactListItem[]>([]);
  protected readonly contactSearchOpen = signal(false);

  private readonly contactQuery$ = new Subject<string>();

  protected readonly scheduledAtControl = this.fb.control('', {
    nonNullable: true,
    validators: [Validators.required],
  });

  protected readonly form = this.fb.group({
    title: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    purpose: this.fb.control('', { nonNullable: true }),
    scheduled_at: this.scheduledAtControl,
    duration_min: this.fb.control<number>(60, {
      nonNullable: true,
      validators: [Validators.required, Validators.min(1), Validators.max(24 * 60)],
    }),
    location: this.fb.control('', { nonNullable: true }),
  });

  readonly canSubmit = computed(
    () => this.me() !== null && !this.submitting(),
  );

  ngOnInit(): void {
    this.auth
      .me()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (me) => this.me.set(me),
        error: () => this.me.set(null),
      });

    this.contactQuery$
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        switchMap((q) =>
          this.contactsApi.list({ q: q || undefined, size: 8 }),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => this.contactResults.set(resp.items),
        error: () => this.contactResults.set([]),
      });
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
    this.submitError.set(null);
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
      this.submitError.set('Please pick a contact.');
      return;
    }
    const user = this.me();
    if (!user) {
      this.submitError.set('Could not resolve the current user.');
      return;
    }
    this.submitError.set(null);
    this.conflicts.set([]);
    this.submitting.set(true);

    const raw = this.form.getRawValue();
    const payload: AppointmentCreate = {
      contact_id: contact.id,
      title: raw.title.trim(),
      purpose: raw.purpose.trim() || null,
      scheduled_at: this.toIsoFromLocal(raw.scheduled_at),
      duration_min: Number(raw.duration_min),
      location: raw.location.trim() || null,
      assigned_to_id: user.id,
    };

    this.api
      .create(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (appt) => {
          this.submitting.set(false);
          this.created.emit(appt);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          if (err.status === 409) {
            const body = err.error as Partial<ConflictBody>;
            this.conflicts.set(body?.conflicts ?? []);
            this.submitError.set(
              body?.message
                ?? 'Time conflict: this slot is already booked.',
            );
          } else {
            this.submitError.set(
              extractApiError(err) ?? 'Could not create appointment.',
            );
          }
        },
      });
  }

  protected conflictLabel(id: string): string {
    return this.conflictTitleFor(id) ?? id.slice(0, 8) + 'â€¦';
  }

  /** Convert `<input type="datetime-local">` value â†’ backend ISO. */
  private toIsoFromLocal(value: string): string {
    const d = new Date(value);
    return d.toISOString();
  }

  /** Convert a Date â†’ "YYYY-MM-DDTHH:mm" for <input type="datetime-local">. */
  private toDatetimeLocalString(d: Date, hour: number): string {
    const local = new Date(
      d.getFullYear(),
      d.getMonth(),
      d.getDate(),
      hour,
      0,
      0,
      0,
    );
    const pad = (n: number) => String(n).padStart(2, '0');
    return (
      `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())}`
      + `T${pad(local.getHours())}:${pad(local.getMinutes())}`
    );
  }

}

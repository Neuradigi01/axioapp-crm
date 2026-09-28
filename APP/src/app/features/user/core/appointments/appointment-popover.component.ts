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
import { format } from 'date-fns';
import { LucideAngularModule } from 'lucide-angular';

import { FurnitureAuthService } from '../auth/auth.service';
import { Appointment } from './appointments-api.service';

/**
 * Compact popover surfacing the four hot actions for an appointment:
 * Reassign / Reschedule / Mark completed / Cancel. Same component
 * mounted from both the calendar event-click and the list row so the
 * interaction stays uniform.
 *
 * Permissions are checked here so callers don't need to recompute the
 * same gates everywhere. Each button emits an intent (`(reassign)`,
 * `(reschedule)`, `(markCompleted)`, `(cancelAppt)`, `(deleteAppt)`)
 * — the parent owns the actual API call so a 422 (state) or 409
 * (conflict) can surface in the right modal.
 *
 * Buttons whose backing state-machine transition isn't allowed are
 * hidden (mirrors `core/appointments/status_workflow.ALLOWED_TRANSITIONS`):
 *   scheduled → completed, no_show, cancelled
 *   completed → (terminal)
 *   no_show / cancelled → scheduled  (re-book — handled via reschedule)
 */
const ALLOWED_FROM_STATUS: Record<Appointment['status'], ReadonlyArray<string>> = {
  scheduled: ['completed', 'no_show', 'cancelled'],
  completed: [],
  no_show: ['scheduled'],
  cancelled: ['scheduled'],
};

@Component({
  selector: 'app-appointment-popover',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './appointment-popover.component.html',
})
export class AppointmentPopoverComponent {
  private readonly auth = inject(FurnitureAuthService);

  protected readonly _appointment = signal<Appointment | null>(null);

  @Input() set appointment(value: Appointment | null) {
    this._appointment.set(value);
  }

  /** Contact details of the appointment's contact, resolved by the
   *  parent from its contacts map (the appointment row only carries the
   *  id). Phone / email render as tap-to-call / tap-to-mail links. */
  @Input() contactName: string | null = null;
  @Input() contactPhone: string | null = null;
  @Input() contactEmail: string | null = null;

  @Output() readonly reassign = new EventEmitter<void>();
  @Output() readonly reschedule = new EventEmitter<void>();
  @Output() readonly markCompleted = new EventEmitter<void>();
  @Output() readonly markNoShow = new EventEmitter<void>();
  @Output() readonly cancelAppt = new EventEmitter<void>();
  @Output() readonly deleteAppt = new EventEmitter<void>();
  @Output() readonly dismiss = new EventEmitter<void>();

  protected readonly canWrite = computed(() => this.auth.hasPermission('appointments.write'));

  /** Formatted "5 Aug 2026, 15:30" for the header — mirrors the row's
   *  time chip but with the day + month prefix so the popover reads
   *  standalone without needing to look back at the list row. */
  protected readonly whenLabel = computed<string | null>(() => {
    const a = this._appointment();
    if (!a) return null;
    return format(new Date(a.scheduled_at), 'd MMM yyyy, HH:mm');
  });

  /** Reassign is only meaningful on `scheduled` appointments — reassigning
   *  a completed / cancelled / no-show slot has no operational effect and
   *  would rewrite history. */
  protected readonly canReassign = computed(() => {
    const a = this._appointment();
    if (!a) return false;
    return this.auth.hasPermission('appointments.reassign') && a.status === 'scheduled';
  });

  /** Reschedule is allowed on `scheduled` (change slot) and `no_show`
   *  (they didn't show up — book them again for a new time). Not on
   *  `completed` (already happened) or `cancelled` (a cancelled
   *  appointment shouldn't be re-woken from a status menu; if the
   *  operator changed their mind, the right flow is to book a new
   *  appointment). */
  protected readonly canReschedule = computed(() => {
    const a = this._appointment();
    if (!a) return false;
    return this.canWrite() && (a.status === 'scheduled' || a.status === 'no_show');
  });

  /** Status-machine gate for "Mark completed" — only valid from `scheduled`. */
  protected readonly canMarkCompleted = computed(() => {
    const a = this._appointment();
    if (!a) return false;
    return this.canWrite() && ALLOWED_FROM_STATUS[a.status].includes('completed');
  });

  /** Status-machine gate for "Mark no-show" — only valid from `scheduled`. */
  protected readonly canMarkNoShow = computed(() => {
    const a = this._appointment();
    if (!a) return false;
    return this.canWrite() && ALLOWED_FROM_STATUS[a.status].includes('no_show');
  });

  /** Status-machine gate for "Cancel" — only valid from `scheduled`. */
  protected readonly canCancel = computed(() => {
    const a = this._appointment();
    if (!a) return false;
    return this.canWrite() && ALLOWED_FROM_STATUS[a.status].includes('cancelled');
  });

  /** Delete is only offered on TERMINAL states (cancelled / completed /
   *  no_show). A scheduled appointment should be cancelled first — the
   *  two-step flow prevents accidental hard-deletes of active bookings
   *  and preserves the audit trail (cancel logs a reason before the
   *  row goes). Requires the same write permission as cancel. */
  protected readonly canDelete = computed(() => {
    const a = this._appointment();
    if (!a) return false;
    return (
      this.canWrite() &&
      (a.status === 'cancelled' || a.status === 'completed' || a.status === 'no_show')
    );
  });

  /** True when at least one action button is renderable — drives the
   *  "This appointment is cancelled…" hint that replaces an empty
   *  button grid so the popover doesn't look broken. */
  protected readonly hasAnyAction = computed(() => {
    return (
      this.canReassign() ||
      this.canReschedule() ||
      this.canMarkCompleted() ||
      this.canMarkNoShow() ||
      this.canCancel() ||
      this.canDelete()
    );
  });
}

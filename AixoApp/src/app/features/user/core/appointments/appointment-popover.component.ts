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
 * `(reschedule)`, `(markCompleted)`, `(cancelAppt)`) — the parent
 * owns the actual API call so a 422 (state) or 409 (conflict) can
 * surface in the right modal.
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

  @Output() readonly reassign = new EventEmitter<void>();
  @Output() readonly reschedule = new EventEmitter<void>();
  @Output() readonly markCompleted = new EventEmitter<void>();
  @Output() readonly markNoShow = new EventEmitter<void>();
  @Output() readonly cancelAppt = new EventEmitter<void>();
  @Output() readonly dismiss = new EventEmitter<void>();

  protected readonly canWrite = computed(() => this.auth.hasPermission('appointments.write'));

  /** Reassign is only meaningful on `scheduled` appointments — reassigning
   *  a completed / cancelled / no-show slot has no operational effect and
   *  would rewrite history. */
  protected readonly canReassign = computed(() => {
    const a = this._appointment();
    if (!a) return false;
    return this.auth.hasPermission('appointments.reassign') && a.status === 'scheduled';
  });

  /** Reschedule is allowed on `scheduled` (change slot), `no_show`, and
   *  `cancelled` (rebook). Not on `completed` — the appointment already
   *  happened. */
  protected readonly canReschedule = computed(() => {
    const a = this._appointment();
    if (!a) return false;
    return this.canWrite() && a.status !== 'completed';
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
}

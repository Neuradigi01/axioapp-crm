import { ChangeDetectionStrategy, Component, signal } from '@angular/core';

import { BookAppointmentModalComponent } from '../../appointments/book-appointment-modal.component';
import { Appointment } from '../../appointments/appointments-api.service';

/**
 * Book Appointment tab — a thin shell that surfaces the existing
 * `BookAppointmentModalComponent` from Step 2.14 directly inside the
 * Call Center page (rule: reuse existing components). The list of
 * already-booked appointments is intentionally NOT shown here; this
 * tab is for booking from a phone interaction. The Appointments page
 * is the authoritative list view.
 */
@Component({
  selector: 'app-call-book-appointment-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [BookAppointmentModalComponent],
  templateUrl: './book-appointment.component.html',
})
export class CallBookAppointmentTabComponent {
  protected readonly modalOpen = signal(false);
  protected readonly lastCreatedTitle = signal<string | null>(null);

  protected open(): void {
    this.modalOpen.set(true);
  }

  protected onCreated(appt: Appointment): void {
    this.lastCreatedTitle.set(appt.title);
    this.modalOpen.set(false);
  }

  protected onCancel(): void {
    this.modalOpen.set(false);
  }
}

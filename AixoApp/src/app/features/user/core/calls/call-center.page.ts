import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { CallLogsTabComponent } from './tabs/logs.component';
import { CallPhoneBookTabComponent } from './tabs/phone-book.component';
import { CallTranscriptsTabComponent } from './tabs/transcripts.component';
import { CallBookAppointmentTabComponent } from './tabs/book-appointment.component';
import { CallAnalyticsTabComponent } from './tabs/analytics.component';

export type CallTabId = 'logs' | 'phone-book' | 'transcripts' | 'book-appointment' | 'analytics';

/**
 * Call Center page — five-tab host matching the master prompt's
 * screenshot: Call Logs · Phone Book · Transcripts · Book Appointment
 * · Analytics. Children own their own data; this page just routes
 * between them so switching tabs is instant and stateful.
 */
@Component({
  selector: 'app-call-center-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LucideAngularModule,
    CallLogsTabComponent,
    CallPhoneBookTabComponent,
    CallTranscriptsTabComponent,
    CallBookAppointmentTabComponent,
    CallAnalyticsTabComponent,
  ],
  templateUrl: './call-center.page.html',
})
export class CallCenterPageComponent {
  protected readonly activeTab = signal<CallTabId>('logs');

  protected readonly tabs: ReadonlyArray<{ id: CallTabId; label: string }> = [
    { id: 'logs', label: 'Call Logs' },
    { id: 'phone-book', label: 'Phone Book' },
    { id: 'transcripts', label: 'Transcripts' },
    { id: 'book-appointment', label: 'Book Appointment' },
    { id: 'analytics', label: 'Analytics' },
  ];

  protected setTab(t: CallTabId): void {
    this.activeTab.set(t);
  }
}

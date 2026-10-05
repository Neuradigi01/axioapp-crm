import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { CallLogsTabComponent } from './tabs/logs.component';
import { CallPhoneBookTabComponent } from './tabs/phone-book.component';
import { CallTranscriptsTabComponent } from './tabs/transcripts.component';
import { CallBookAppointmentTabComponent } from './tabs/book-appointment.component';
import { CallAnalyticsTabComponent } from './tabs/analytics.component';
import { MobileSelectComponent, MobileSelectOption } from '../shared/forms/mobile-select.component';

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
    MobileSelectComponent,
    CallLogsTabComponent,
    CallPhoneBookTabComponent,
    CallTranscriptsTabComponent,
    CallBookAppointmentTabComponent,
    CallAnalyticsTabComponent,
  ],
  templateUrl: './call-center.page.html',
})
export class CallCenterPageComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly activeTab = signal<CallTabId>('logs');

  /** Bumped whenever the header's "Log call" button is clicked so the
   *  logs tab (which owns the modal) reacts and opens the composer.
   *  Signal-based trigger avoids threading a service just for one
   *  cross-component event. */
  protected readonly logCallTrigger = signal(0);

  protected readonly tabs: ReadonlyArray<{ id: CallTabId; label: string }> = [
    { id: 'logs', label: 'Call Logs' },
    { id: 'phone-book', label: 'Phone Book' },
    { id: 'transcripts', label: 'Transcripts' },
    { id: 'book-appointment', label: 'Book Appointment' },
    { id: 'analytics', label: 'Analytics' },
  ];

  /** Same tab list shaped for the mobile `<crm-mobile-select>` picker. */
  protected readonly tabOptions: ReadonlyArray<MobileSelectOption> = this.tabs.map((t) => ({
    value: t.id,
    label: t.label,
  }));

  constructor() {
    // `?tab=` keeps the open tab across refresh / shared links / back.
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const t = params.get('tab');
      this.activeTab.set(this.isTab(t) ? t : 'logs');
    });
  }

  private isTab(v: string | null): v is CallTabId {
    return this.tabs.some((t) => t.id === v);
  }

  protected setTab(t: CallTabId): void {
    this.activeTab.set(t);
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { tab: t === 'logs' ? null : t },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  /** Bridge from the mobile-select `valueChange` (string) to the typed
   *  `CallTabId`. */
  protected setTabFromValue(v: string): void {
    if (this.isTab(v)) this.setTab(v);
  }

  /** Page-header "Log call" click. Always jumps to the Logs tab first
   *  (so the modal appears in the right context) and then bumps the
   *  trigger the tab watches. */
  protected onLogCall(): void {
    this.setTab('logs');
    this.logCallTrigger.update((v) => v + 1);
  }
}

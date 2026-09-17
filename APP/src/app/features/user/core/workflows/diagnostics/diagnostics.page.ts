import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subject, debounceTime, switchMap } from 'rxjs';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { ContactListItem, ContactsApiService } from '../../contacts/contacts-api.service';
import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../shared/forms/mobile-select.component';
import {
  WorkflowDiagnosticsEntry,
  WorkflowDiagnosticsResponse,
  WorkflowsApiService,
} from '../workflows-api.service';
import { ConditionTraceComponent } from './condition-trace.component';

/**
 * Step 19 — "why didn't this workflow fire?" diagnostics page.
 *
 * URL: `/user/workflows/diagnostics`. Permission gated server-side
 * on `workflows.view_diagnostics` (Owner / Admin only by default).
 *
 * The trace runs against a synthesised event payload built from the
 * contact's columns + custom_data, so the operator can see the
 * exact rejection reason without having to wait for a real event.
 */

// Event-type catalogue — mirrors the backend `ALL_EVENTS` tuple.
// Hard-coded list keeps the page from a separate /events endpoint
// round-trip; refresh on any catalog change. Order matches the
// backend's domain grouping. Label mirrors the raw event key so
// operators pasting an event name from logs can spot-match; group
// drives the sticky headers in the mobile-select picker.
const EVENT_TYPES: readonly MobileSelectOption[] = [
  { value: 'lead.created', label: 'lead.created', group: 'Leads' },
  { value: 'lead.status_changed', label: 'lead.status_changed', group: 'Leads' },
  { value: 'lead.score_threshold', label: 'lead.score_threshold', group: 'Leads' },
  { value: 'lead.assigned', label: 'lead.assigned', group: 'Leads' },
  { value: 'lead.converted', label: 'lead.converted', group: 'Leads' },
  { value: 'lead.stale_7d', label: 'lead.stale_7d', group: 'Leads' },
  { value: 'lead.stale_30d', label: 'lead.stale_30d', group: 'Leads' },
  { value: 'lead.stale_90d', label: 'lead.stale_90d', group: 'Leads' },
  { value: 'contact.created', label: 'contact.created', group: 'Contacts' },
  { value: 'contact.birthday', label: 'contact.birthday', group: 'Contacts' },
  { value: 'contact.anniversary', label: 'contact.anniversary', group: 'Contacts' },
  { value: 'contact.opt_in_changed', label: 'contact.opt_in_changed', group: 'Contacts' },
  { value: 'quote.sent', label: 'quote.sent', group: 'Sales' },
  { value: 'quote.viewed', label: 'quote.viewed', group: 'Sales' },
  { value: 'quote.accepted', label: 'quote.accepted', group: 'Sales' },
  { value: 'quote.rejected', label: 'quote.rejected', group: 'Sales' },
  { value: 'invoice.sent', label: 'invoice.sent', group: 'Sales' },
  { value: 'invoice.paid', label: 'invoice.paid', group: 'Sales' },
  { value: 'invoice.overdue_7d', label: 'invoice.overdue_7d', group: 'Sales' },
  { value: 'order.placed', label: 'order.placed', group: 'Sales' },
  { value: 'order.delivered', label: 'order.delivered', group: 'Sales' },
];

@Component({
  selector: 'app-workflow-diagnostics-page',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    LucideAngularModule,
    ConditionTraceComponent,
    MobileSelectComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './diagnostics.page.html',
})
export class WorkflowDiagnosticsPageComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly contactQuery = signal('');
  readonly contactResults = signal<ContactListItem[]>([]);
  readonly selectedContact = signal<ContactListItem | null>(null);
  readonly eventType = signal('lead.created');
  readonly eventTypes = EVENT_TYPES;

  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly trace = signal<WorkflowDiagnosticsResponse | null>(null);

  readonly expandedEntry = signal<string | null>(null);
  /** Whether the contact list dropdown is currently expanded. Anchored
   *  to focus so the pre-fetched roster appears on click without
   *  requiring the operator to type first. */
  readonly contactListOpen = signal(false);

  readonly canRun = computed(() => !!this.selectedContact() && !!this.eventType() && !this.busy());

  private readonly searchSubject = new Subject<string>();

  constructor() {
    this.searchSubject
      .pipe(
        debounceTime(220),
        switchMap((q) => this.contactsApi.list({ q: q || undefined, size: 12 })),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => this.contactResults.set(resp.items),
        error: () => this.contactResults.set([]),
      });
    // Pre-fetch the first page of contacts on init so the dropdown has
    // something to show as soon as the operator clicks the input — no
    // "type to search" dead-first-click.
    this.searchSubject.next('');
  }

  onSearchInput(value: string): void {
    this.contactQuery.set(value);
    this.searchSubject.next(value);
  }

  onSearchFocus(): void {
    this.contactListOpen.set(true);
    // Re-fetch the empty roster on focus after a pick so returning to
    // the input surfaces alternatives, not the stale single-match
    // list left over from the previous selection.
    if (this.contactResults().length === 0 || this.selectedContact()) {
      this.searchSubject.next(this.contactQuery());
    }
  }

  onSearchBlur(): void {
    // Delay so click-on-result registers before the list hides.
    setTimeout(() => this.contactListOpen.set(false), 150);
  }

  pickContact(contact: ContactListItem): void {
    this.selectedContact.set(contact);
    this.contactQuery.set(contact.full_name);
    this.contactResults.set([]);
  }

  runTrace(): void {
    const contact = this.selectedContact();
    const eventType = this.eventType();
    if (!contact || !eventType) return;
    this.busy.set(true);
    this.error.set(null);
    this.api
      .traceDiagnostics({ contact_id: contact.id, event_type: eventType })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.trace.set(resp);
          this.busy.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Trace failed.');
          this.busy.set(false);
        },
      });
  }

  toggleEntry(workflowId: string): void {
    this.expandedEntry.update((current) => (current === workflowId ? null : workflowId));
  }

  entryClasses(entry: WorkflowDiagnosticsEntry): string {
    if (entry.eligible) {
      return 'border-emerald-200 bg-emerald-50/40';
    }
    return 'border-subtle bg-surface';
  }
}

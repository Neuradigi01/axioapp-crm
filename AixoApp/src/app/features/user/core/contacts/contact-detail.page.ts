import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import { ActivityTimelineComponent } from '../activities/activity-timeline.component';
import { AddNoteComponent } from '../activities/add-note.component';
import { Activity } from '../activities/activities-api.service';
import { ContactAutomationsTabComponent } from './contact-detail/automations-tab.component';
import { TasksPanelComponent } from '../tasks/tasks-panel.component';
import { FurnitureAuthService } from '../auth/auth.service';
import { ConfirmDialogComponent } from '../shared/confirm-dialog/confirm-dialog.component';
import { MailLinkDirective } from '../shared/directives/mail-link.directive';
import { PhoneLinkDirective } from '../shared/directives/phone-link.directive';
import { WhatsappLinkDirective } from '../shared/directives/whatsapp-link.directive';
import { FieldDef } from '../shared/dynamic-form/types';
import { RelativeTimePipe } from '../shared/pipes/relative-time.pipe';
import {
  ReassignConfirm,
  ReassignModalComponent,
} from '../shared/reassign-modal/reassign-modal.component';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import { Contact, ContactCreate, ContactUpdate, ContactsApiService } from './contacts-api.service';
import { ContactFormModalComponent } from './contact-form-modal.component';
import { MergeContactModalComponent } from './merge-contact-modal.component';
import { OptInChipComponent } from './opt-in/opt-in-chip.component';
import { OptInSectionComponent } from './opt-in/opt-in-section.component';
import { extractApiError } from '@core/services/api-error.util';
import { initials } from '@core/services/text.util';

type DetailTab = 'overview' | 'activities' | 'tasks' | 'automations';

const TABS: ReadonlyArray<{ id: DetailTab; label: string }> = [
  { id: 'overview', label: 'Overview' },
  // Activities is the canonical notes + timeline surface: `AddNoteComponent`
  // posts `type=note` Activity rows and the timeline renders them. No
  // separate Notes tab.
  { id: 'activities', label: 'Activities' },
  { id: 'tasks', label: 'Tasks' },
  // tasks/automation-engine Step 9 — per-contact run history.
  { id: 'automations', label: 'Automations' },
];

@Component({
  selector: 'app-contact-detail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    LucideAngularModule,
    ContactFormModalComponent,
    MergeContactModalComponent,
    ActivityTimelineComponent,
    AddNoteComponent,
    ContactAutomationsTabComponent,
    TasksPanelComponent,
    RelativeTimePipe,
    ReassignModalComponent,
    ConfirmDialogComponent,
    PhoneLinkDirective,
    WhatsappLinkDirective,
    MailLinkDirective,
    OptInSectionComponent,
    OptInChipComponent,
  ],
  templateUrl: './contact-detail.page.html',
})
export class ContactDetailPageComponent implements OnInit {
  protected readonly initials = initials;
  private readonly api = inject(ContactsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly usersDir = inject(UsersDirectoryService);
  private readonly auth = inject(FurnitureAuthService);

  /** Reassign + delete confirmation modal state. */
  readonly reassignOpen = signal(false);
  readonly reassignSubmitting = signal(false);
  readonly reassignError = signal<string | null>(null);

  readonly deleteOpen = signal(false);
  readonly deleteSubmitting = signal(false);
  readonly deleteError = signal<string | null>(null);

  /** Merge modal state. Open shows a search box + confirm; on merged
   *  we refresh the primary contact signal so custom_data + tags
   *  reflect the union that came back from the server. */
  readonly mergeOpen = signal(false);

  /** DPDP right-to-be-forgotten (U7) — confirm dialog state. */
  readonly anonymiseOpen = signal(false);
  readonly anonymiseSubmitting = signal(false);
  readonly anonymiseError = signal<string | null>(null);
  readonly anonymiseReason = signal('');

  /** True when the loaded contact has already been anonymised — used
   *  to hide the Anonymise button + show the "Anonymised" chip. */
  readonly isAnonymised = computed(() => this.contact()?.anonymised_at != null);

  /** Tied to `*ngIf` on the pencil-icon — junior staff shouldn't see it. */
  readonly canReassign = computed(() => this.auth.hasPermission('contacts.reassign'));

  /** Owner-id → "Full Name" lookup so the header can show a name
   * without a per-contact round-trip. */
  readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  protected ownerLabel(assignedTo: string | null): string {
    if (!assignedTo) return 'Unassigned';
    for (const u of this.users()) {
      if (u.id === assignedTo) return u.full_name;
    }
    return 'Unknown';
  }

  readonly contact = signal<Contact | null>(null);
  readonly fields = signal<FieldDef[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);

  readonly tabs = TABS;
  readonly activeTab = signal<DetailTab>('overview');

  /** Live handle on the timeline so add-note can prepend without a refetch. */
  protected readonly timeline = viewChild(ActivityTimelineComponent);

  /** Modal state: null = closed, Contact = edit. (No create from detail.) */
  readonly editingContact = signal<Contact | null>(null);
  readonly modalOpen = computed(() => this.editingContact() !== null);
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);

  protected onNoteCreated(activity: Activity): void {
    this.timeline()?.prepend(activity);
  }

  readonly customFields = computed(() => {
    const c = this.contact();
    if (c === null) return [] as { label: string; value: string }[];
    const data = c.custom_data ?? {};
    return this.fields().map((def) => ({
      label: def.field_label,
      value: this.formatValue(def, data[def.field_key]),
    }));
  });

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) {
      this.loadError.set('Contact id missing in URL.');
      this.loading.set(false);
      return;
    }
    this.loadContact(id);
    this.loadFields();
  }

  protected setTab(tab: DetailTab): void {
    this.activeTab.set(tab);
  }

  protected openEdit(): void {
    const c = this.contact();
    if (c) this.editingContact.set(c);
  }

  protected closeModal(): void {
    this.editingContact.set(null);
    this.formError.set(null);
    this.submitting.set(false);
  }

  protected onSave(event: { create?: ContactCreate; update?: ContactUpdate }): void {
    const c = this.contact();
    if (!event.update || !c) return;
    this.submitting.set(true);
    this.formError.set(null);
    this.api
      .update(c.id, event.update)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.contact.set(updated);
          this.submitting.set(false);
          this.closeModal();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.formError.set(extractApiError(err) ?? 'Could not save contact.');
        },
      });
  }

  protected onDelete(): void {
    this.deleteError.set(null);
    this.deleteOpen.set(true);
  }

  protected closeDelete(): void {
    this.deleteOpen.set(false);
    this.deleteSubmitting.set(false);
    this.deleteError.set(null);
  }

  protected confirmDelete(): void {
    const c = this.contact();
    if (!c) return;
    this.deleteSubmitting.set(true);
    this.deleteError.set(null);
    this.api
      .delete(c.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleteSubmitting.set(false);
          this.closeDelete();
          this.router.navigate(['/user/contacts']);
        },
        error: (err: HttpErrorResponse) => {
          this.deleteSubmitting.set(false);
          this.deleteError.set(extractApiError(err) ?? 'Could not delete contact.');
        },
      });
  }

  protected openAnonymise(): void {
    this.anonymiseError.set(null);
    this.anonymiseReason.set('');
    this.anonymiseOpen.set(true);
  }

  protected closeAnonymise(): void {
    this.anonymiseOpen.set(false);
    this.anonymiseSubmitting.set(false);
    this.anonymiseError.set(null);
  }

  protected onAnonymiseReasonInput(event: Event): void {
    this.anonymiseReason.set((event.target as HTMLInputElement).value);
  }

  protected confirmAnonymise(): void {
    const c = this.contact();
    if (!c) return;
    this.anonymiseSubmitting.set(true);
    this.anonymiseError.set(null);
    const reason = this.anonymiseReason().trim() || null;
    this.api
      .anonymise(c.id, reason)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.contact.set(updated);
          this.anonymiseSubmitting.set(false);
          this.closeAnonymise();
        },
        error: (err: HttpErrorResponse) => {
          this.anonymiseSubmitting.set(false);
          this.anonymiseError.set(extractApiError(err) ?? 'Could not anonymise contact.');
        },
      });
  }

  protected openMerge(): void {
    this.mergeOpen.set(true);
  }

  protected closeMerge(): void {
    this.mergeOpen.set(false);
  }

  protected onMerged(primary: Contact): void {
    // Refresh the header with the union'd primary and refetch the
    // timeline so the "merged from..." breadcrumb appears.
    this.contact.set(primary);
    this.mergeOpen.set(false);
    this.timeline()?.reload();
  }

  protected openReassign(): void {
    this.reassignError.set(null);
    this.reassignOpen.set(true);
  }

  protected closeReassign(): void {
    this.reassignOpen.set(false);
    this.reassignSubmitting.set(false);
    this.reassignError.set(null);
  }

  protected onReassign(payload: ReassignConfirm): void {
    const c = this.contact();
    if (!c) return;
    this.reassignSubmitting.set(true);
    this.reassignError.set(null);
    this.api
      .reassign(c.id, { userId: payload.userId, note: payload.note })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.contact.set(updated);
          this.reassignSubmitting.set(false);
          this.closeReassign();
          // Activity timeline picks up the audit row on its next paint via
          // the live signal; we don't need to force a refresh here.
        },
        error: (err: HttpErrorResponse) => {
          this.reassignSubmitting.set(false);
          this.reassignError.set(extractApiError(err) ?? 'Could not reassign contact.');
        },
      });
  }

  private loadContact(id: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .get(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (c) => {
          this.contact.set(c);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(extractApiError(err) ?? 'Could not load contact.');
          this.loading.set(false);
        },
      });
  }

  private loadFields(): void {
    this.api
      .renderFields()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (defs) => this.fields.set(defs),
        // Custom-field defs are nice-to-have; a failure here doesn't
        // block the standard fields from rendering. We silently skip
        // the Custom block instead of surfacing an error.
        error: () => this.fields.set([]),
      });
  }

  private formatValue(def: FieldDef, value: unknown): string {
    if (value === null || value === undefined || value === '') return '—';
    if (Array.isArray(value)) return value.length === 0 ? '—' : value.join(', ');
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (def.field_type === 'currency' && typeof value === 'number') {
      return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        maximumFractionDigits: 2,
      }).format(value);
    }
    return String(value);
  }
}

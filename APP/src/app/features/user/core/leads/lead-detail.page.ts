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
import { switchMap } from 'rxjs/operators';

import { ActivityTimelineComponent } from '../activities/activity-timeline.component';
import { AddNoteComponent } from '../activities/add-note.component';
import { Activity } from '../activities/activities-api.service';
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
import { Contact, ContactsApiService } from '../contacts/contacts-api.service';
import { Lead, LeadCreate, LeadUpdate, LeadsApiService } from './leads-api.service';
import { LeadFormModalComponent } from './lead-form-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import { initials } from '@core/services/text.util';

type DetailTab = 'overview' | 'activities' | 'notes' | 'tasks';

const TABS: ReadonlyArray<{ id: DetailTab; label: string; placeholderStep: string | null }> = [
  { id: 'overview', label: 'Overview', placeholderStep: null },
  { id: 'activities', label: 'Activities', placeholderStep: null },
  { id: 'notes', label: 'Notes', placeholderStep: 'later' },
  { id: 'tasks', label: 'Tasks', placeholderStep: null },
];

/** Pipeline-stage pill colour mapping. Matches the badges used on the
 * pipeline board so the stage indicator on the detail page looks the
 * same as the column the lead lives in. */
const STAGE_TONES: Record<string, { bg: string; text: string; ring: string }> = {
  new: { bg: 'bg-blue-50', text: 'text-blue-700', ring: 'ring-blue-200' },
  contacted: { bg: 'bg-indigo-50', text: 'text-indigo-700', ring: 'ring-indigo-200' },
  qualified: { bg: 'bg-violet-50', text: 'text-violet-700', ring: 'ring-violet-200' },
  proposal: { bg: 'bg-amber-50', text: 'text-amber-700', ring: 'ring-amber-200' },
  negotiation: { bg: 'bg-orange-50', text: 'text-orange-700', ring: 'ring-orange-200' },
  won: { bg: 'bg-emerald-50', text: 'text-emerald-700', ring: 'ring-emerald-200' },
  lost: { bg: 'bg-rose-50', text: 'text-rose-700', ring: 'ring-rose-200' },
};

@Component({
  selector: 'app-lead-detail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    LucideAngularModule,
    LeadFormModalComponent,
    ActivityTimelineComponent,
    AddNoteComponent,
    TasksPanelComponent,
    RelativeTimePipe,
    ReassignModalComponent,
    ConfirmDialogComponent,
    PhoneLinkDirective,
    WhatsappLinkDirective,
    MailLinkDirective,
  ],
  templateUrl: './lead-detail.page.html',
})
export class LeadDetailPageComponent implements OnInit {
  protected readonly initials = initials;
  private readonly api = inject(LeadsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly usersDir = inject(UsersDirectoryService);
  private readonly auth = inject(FurnitureAuthService);

  readonly reassignOpen = signal(false);
  readonly reassignSubmitting = signal(false);
  readonly reassignError = signal<string | null>(null);

  readonly deleteOpen = signal(false);
  readonly deleteSubmitting = signal(false);
  readonly deleteError = signal<string | null>(null);

  readonly canReassign = computed(() => this.auth.hasPermission('leads.reassign'));

  readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  protected ownerLabel(assignedTo: string | null): string {
    if (!assignedTo) return 'Unassigned';
    for (const u of this.users()) {
      if (u.id === assignedTo) return u.full_name;
    }
    return 'Unknown';
  }

  readonly lead = signal<Lead | null>(null);
  readonly contact = signal<Contact | null>(null);
  readonly fields = signal<FieldDef[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);

  readonly tabs = TABS;
  readonly activeTab = signal<DetailTab>('overview');

  protected readonly timeline = viewChild(ActivityTimelineComponent);

  readonly editingLead = signal<Lead | null>(null);
  readonly modalOpen = computed(() => this.editingLead() !== null);
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);

  protected onNoteCreated(activity: Activity): void {
    this.timeline()?.prepend(activity);
  }

  readonly customFields = computed(() => {
    const l = this.lead();
    if (l === null) return [] as { label: string; value: string }[];
    const data = l.custom_data ?? {};
    return this.fields().map((def) => ({
      label: def.field_label,
      value: this.formatValue(def, data[def.field_key]),
    }));
  });

  readonly placeholderForActiveTab = computed<string | null>(() => {
    const tab = TABS.find((t) => t.id === this.activeTab());
    return tab?.placeholderStep ?? null;
  });

  /** Pretty-print the lead's attribution JSONB column. Each row is a
   *  key-value pair the operator can scan. Empty payload renders the
   *  block as "Captured directly — no attribution metadata." */
  readonly attributionEntries = computed(() => {
    const l = this.lead();
    if (!l || !l.attribution) return [] as { key: string; value: string }[];
    const out: { key: string; value: string }[] = [];
    for (const [k, v] of Object.entries(l.attribution)) {
      if (v === null || v === undefined || v === '') continue;
      out.push({ key: k, value: String(v) });
    }
    return out;
  });

  readonly stageTone = computed(() => {
    const stage = (this.lead()?.pipeline_stage ?? '').toLowerCase();
    return (
      STAGE_TONES[stage] ?? {
        bg: 'bg-surface-2',
        text: 'text-default',
        ring: 'border-subtle',
      }
    );
  });

  readonly headerTitle = computed(() => {
    const c = this.contact();
    if (c?.full_name) return c.full_name;
    return 'Lead';
  });

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) {
      this.loadError.set('Lead id missing in URL.');
      this.loading.set(false);
      return;
    }
    this.loadLead(id);
    this.loadFields();
  }

  protected setTab(tab: DetailTab): void {
    this.activeTab.set(tab);
  }

  protected openEdit(): void {
    const l = this.lead();
    if (l) this.editingLead.set(l);
  }

  protected closeModal(): void {
    this.editingLead.set(null);
    this.formError.set(null);
    this.submitting.set(false);
  }

  protected onSave(event: {
    create?: LeadCreate;
    update?: LeadUpdate;
    moveStageTo?: string;
  }): void {
    const l = this.lead();
    if (!event.update || !l) return;
    this.submitting.set(true);
    this.formError.set(null);
    // ``pipeline_stage`` transitions never flow through the plain
    // PATCH — the backend `LeadUpdate` schema deliberately omits it
    // so kanban moves go through `move-stage` (which stamps activity
    // + audit + status sync). Mirror the leads-list page pattern:
    // apply the field-level update, then chain the stage move when
    // the modal reported one.
    const update$ = this.api.update(l.id, event.update);
    const final$ = event.moveStageTo
      ? update$.pipe(switchMap(() => this.api.moveStage(l.id, event.moveStageTo!)))
      : update$;
    final$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (updated) => {
        this.lead.set(updated);
        this.submitting.set(false);
        this.closeModal();
      },
      error: (err: HttpErrorResponse) => {
        this.submitting.set(false);
        this.formError.set(extractApiError(err) ?? 'Could not save lead.');
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
    const l = this.lead();
    if (!l) return;
    this.deleteSubmitting.set(true);
    this.deleteError.set(null);
    this.api
      .delete(l.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleteSubmitting.set(false);
          this.closeDelete();
          this.router.navigate(['/user/leads']);
        },
        error: (err: HttpErrorResponse) => {
          this.deleteSubmitting.set(false);
          this.deleteError.set(extractApiError(err) ?? 'Could not delete lead.');
        },
      });
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
    const l = this.lead();
    if (!l) return;
    this.reassignSubmitting.set(true);
    this.reassignError.set(null);
    this.api
      .reassign(l.id, { userId: payload.userId, note: payload.note })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.lead.set(updated);
          this.reassignSubmitting.set(false);
          this.closeReassign();
        },
        error: (err: HttpErrorResponse) => {
          this.reassignSubmitting.set(false);
          this.reassignError.set(extractApiError(err) ?? 'Could not reassign lead.');
        },
      });
  }

  private loadLead(id: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .get(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (l) => {
          this.lead.set(l);
          this.loading.set(false);
          if (l.contact_id) {
            this.loadContact(l.contact_id);
          }
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(extractApiError(err) ?? 'Could not load lead.');
          this.loading.set(false);
        },
      });
  }

  private loadContact(contactId: string): void {
    this.contactsApi
      .get(contactId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (c) => this.contact.set(c),
        // A contact-fetch failure isn't fatal — the lead detail still
        // renders. The contact card just shows "Could not load contact."
        error: () => this.contact.set(null),
      });
  }

  private loadFields(): void {
    this.api
      .renderFields()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (defs) => this.fields.set(defs),
        error: () => this.fields.set([]),
      });
  }

  /** Resolve the currency to render for money values: lead's
   *  per-row `currency` wins, falling back to the org default.
   *  Prevents USD/EUR orgs from seeing INR symbols on every budget. */
  private resolveCurrency(): string {
    const perLead = this.lead()?.currency ?? null;
    if (perLead) return perLead;
    return this.auth.currentOrg()?.currency || 'INR';
  }

  private formatValue(def: FieldDef, value: unknown): string {
    if (value === null || value === undefined || value === '') return '—';
    if (Array.isArray(value)) return value.length === 0 ? '—' : value.join(', ');
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (def.field_type === 'currency' && typeof value === 'number') {
      return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency: this.resolveCurrency(),
        maximumFractionDigits: 2,
      }).format(value);
    }
    return String(value);
  }

  protected formatBudget(value: string | null): string {
    if (value === null || value === '' || value === undefined) return '—';
    const n = Number(value);
    if (Number.isNaN(n)) return value;
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: this.resolveCurrency(),
      maximumFractionDigits: 2,
    }).format(n);
  }
}

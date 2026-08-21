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
import { PipelineStage, PipelinesApiService } from '../pipelines/pipelines-api.service';
import { Lead, LeadCreate, LeadUpdate, LeadsApiService } from './leads-api.service';
import { LeadFormModalComponent } from './lead-form-modal.component';
import { LeadFollowUpsPanelComponent } from './lead-follow-ups-panel.component';
import { UpdateStatusModalComponent } from './update-status-modal.component';
import {
  LostReasonConfirm,
  LostReasonModalComponent,
} from './lost-reason-modal/lost-reason-modal.component';
import {
  WonCaptureConfirm,
  WonCaptureModalComponent,
} from './won-capture-modal/won-capture-modal.component';
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
  lost: { bg: 'bg-red-500/10', text: 'text-red-400', ring: 'ring-red-500/20' },
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
    LostReasonModalComponent,
    WonCaptureModalComponent,
    UpdateStatusModalComponent,
    LeadFollowUpsPanelComponent,
  ],
  templateUrl: './lead-detail.page.html',
})
export class LeadDetailPageComponent implements OnInit {
  protected readonly initials = initials;
  private readonly api = inject(LeadsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly pipelinesApi = inject(PipelinesApiService);
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

  /** Update-Status quick-action modal (sir's screenshot). Additive
   *  alongside Edit / Delete — the full authoring modal keeps its
   *  own state above. */
  readonly updateStatusOpen = signal(false);

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
  /** Overview-tab follow-ups panel. Ref used to prepend the newly-
   *  created task after the Update Status modal returns without a
   *  full refetch. Optional because the Overview tab may not be the
   *  active tab when the modal saves. */
  protected readonly followUpsPanel = viewChild(LeadFollowUpsPanelComponent);

  readonly editingLead = signal<Lead | null>(null);
  readonly modalOpen = computed(() => this.editingLead() !== null);
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);

  /** Loaded lead pipeline stages — used to pre-check `is_won` / `is_lost`
   *  on the destination stage when the Edit modal reports a
   *  ``moveStageTo``, so the correct capture modal (Won / Lost) opens
   *  before we dispatch the move. Empty until the pipeline API responds. */
  readonly pipelineStages = signal<PipelineStage[]>([]);

  /** Pending payload waiting on a Lost-reason. Mirrors the leads-list
   *  page pattern — same picker component, same downstream call. Held
   *  here so the reason modal can re-issue the update + move-stage on
   *  confirm. */
  readonly pendingLostSave = signal<{ update: LeadUpdate; toStage: string } | null>(null);
  readonly lostReasonSubmitting = signal(false);
  readonly lostReasonError = signal<string | null>(null);

  /** Pending payload waiting on Won-capture. Same up-front check as the
   *  kanban: the backend doesn't 422 on missing won fields, so we open
   *  the modal proactively when the target stage has ``is_won=true``. */
  readonly pendingWonSave = signal<{ update: LeadUpdate; toStage: string } | null>(null);
  readonly wonCaptureSubmitting = signal(false);
  readonly wonCaptureError = signal<string | null>(null);

  /** Suggestion feed for the Won modal's "closed amount" input —
   *  seeds with the lead's own `budget`. */
  readonly pendingWonSuggestion = signal<string | null>(null);

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
    this.loadPipelineStages();
  }

  protected setTab(tab: DetailTab): void {
    this.activeTab.set(tab);
  }

  protected openEdit(): void {
    const l = this.lead();
    if (l) this.editingLead.set(l);
  }

  protected openUpdateStatus(): void {
    // Guard against opening before the lead + pipeline stages settled;
    // the modal's `input.required<Lead>()` would throw at construction
    // time. The button is disabled in that state too.
    if (this.lead() && this.pipelineStages().length > 0) {
      this.updateStatusOpen.set(true);
    }
  }

  protected closeUpdateStatus(): void {
    this.updateStatusOpen.set(false);
  }

  /** Handler for the Update-Status modal's `saved` output. Refreshes
   *  the lead signal so the header pills reflect the new stage /
   *  status / source instantly, reloads the Activities timeline, and
   *  when a follow-up task was created reloads the Follow-Ups panel
   *  so the new row appears without a page refresh. */
  protected onUpdateStatusSaved(event: {
    lead: Lead;
    next_follow_up_task_id: string | null;
  }): void {
    this.lead.set(event.lead);
    this.updateStatusOpen.set(false);
    // Timeline picks up the new `note` + `status_change` activities on
    // the next fetch; force a reload so reps see them without a full
    // page refresh.
    this.timeline()?.reload();
    // Overview-tab follow-ups panel (if mounted) reloads to pick up
    // the just-created task. We reload rather than `prepend()` because
    // the log-update response ships only the task id, not the full
    // Task row — one round-trip is cheaper than adding a get-by-id.
    if (event.next_follow_up_task_id !== null) {
      this.followUpsPanel()?.reload();
    }
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
    // The modal also emits contact-side hints on create; this page is
    // edit-only so we accept-and-ignore them for structural typing.
    contactAction?: 'created' | 'matched';
    contactName?: string;
  }): void {
    const l = this.lead();
    if (!event.update || !l) return;
    // ``pipeline_stage`` transitions never flow through the plain
    // PATCH — the backend `LeadUpdate` schema deliberately omits it
    // so kanban moves go through `move-stage` (which stamps activity
    // + audit + status sync). When the modal reports a
    // ``moveStageTo`` we pre-check the destination stage: if it's
    // Lost we open the reason picker, if it's Won we open the capture
    // modal; either flow re-issues the PATCH + move-stage with the
    // right fields on confirm.
    if (event.moveStageTo) {
      const targetStage = this.pipelineStages().find((s) => s.key === event.moveStageTo);
      if (targetStage?.is_lost) {
        this.pendingLostSave.set({ update: event.update, toStage: event.moveStageTo });
        this.lostReasonError.set(null);
        return;
      }
      if (targetStage?.is_won) {
        this.pendingWonSave.set({ update: event.update, toStage: event.moveStageTo });
        this.pendingWonSuggestion.set(l.budget ?? null);
        this.wonCaptureError.set(null);
        return;
      }
    }
    this.dispatchSave(l.id, event.update, event.moveStageTo);
  }

  protected onLostReasonConfirm(payload: LostReasonConfirm): void {
    const pending = this.pendingLostSave();
    const l = this.lead();
    if (!pending || !l) return;
    this.lostReasonSubmitting.set(true);
    this.lostReasonError.set(null);
    this.api
      .update(l.id, pending.update)
      .pipe(
        switchMap(() =>
          this.api.moveStage(l.id, pending.toStage, {
            lost_reason: payload.lost_reason,
            lost_reason_other: payload.lost_reason_other,
          }),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (updated) => {
          this.lead.set(updated);
          this.lostReasonSubmitting.set(false);
          this.pendingLostSave.set(null);
          this.closeModal();
        },
        error: (err: HttpErrorResponse) => {
          this.lostReasonSubmitting.set(false);
          this.lostReasonError.set(extractApiError(err) ?? 'Could not mark lead as Lost.');
        },
      });
  }

  protected onLostReasonCancel(): void {
    this.pendingLostSave.set(null);
    this.lostReasonError.set(null);
    this.lostReasonSubmitting.set(false);
  }

  protected onWonCaptureConfirm(payload: WonCaptureConfirm): void {
    const pending = this.pendingWonSave();
    const l = this.lead();
    if (!pending || !l) return;
    this.wonCaptureSubmitting.set(true);
    this.wonCaptureError.set(null);
    this.api
      .update(l.id, pending.update)
      .pipe(
        switchMap(() =>
          this.api.moveStage(l.id, pending.toStage, {
            won_value: payload.won_value,
            close_date: payload.close_date,
            won_reason: payload.won_reason,
          }),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (updated) => {
          this.lead.set(updated);
          this.wonCaptureSubmitting.set(false);
          this.pendingWonSave.set(null);
          this.pendingWonSuggestion.set(null);
          this.closeModal();
        },
        error: (err: HttpErrorResponse) => {
          this.wonCaptureSubmitting.set(false);
          this.wonCaptureError.set(extractApiError(err) ?? 'Could not mark lead as Won.');
        },
      });
  }

  protected onWonCaptureCancel(): void {
    this.pendingWonSave.set(null);
    this.pendingWonSuggestion.set(null);
    this.wonCaptureError.set(null);
    this.wonCaptureSubmitting.set(false);
  }

  private dispatchSave(id: string, update: LeadUpdate, moveStageTo?: string): void {
    this.submitting.set(true);
    this.formError.set(null);
    const update$ = this.api.update(id, update);
    const final$ = moveStageTo
      ? update$.pipe(switchMap(() => this.api.moveStage(id, moveStageTo)))
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

  private loadPipelineStages(): void {
    this.pipelinesApi
      .getByKey('leads')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (p) => this.pipelineStages.set(p.stages ?? []),
        // Non-blocking: if the pipeline load fails, the Lost/Won
        // interception silently no-ops and the standard save path
        // handles it. Field-level errors surface elsewhere on the page.
        error: () => this.pipelineStages.set([]),
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

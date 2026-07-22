import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Output,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { Subject, of } from 'rxjs';
import { catchError, debounceTime, switchMap } from 'rxjs/operators';

import { ConversationChannel } from '../conversations/conversations-api.service';
import { SendFromPickerComponent } from '../whatsapp/shared/send-from-picker.component';
import { AbTestSectionComponent } from './ab/ab-test-section.component';
import { extractApiError } from '@core/services/api-error.util';
import {
  ContactGroup,
  ContactGroupsApiService,
  GroupFilter,
} from '../contacts/groups/groups-api.service';
import { ContactListItem, ContactsApiService } from '../contacts/contacts-api.service';
import {
  IntegrationsApiService,
  WhatsAppCapacity,
} from '../settings/integrations/integrations-api.service';
import { EmailAccount, EmailAccountsApiService } from '../services/email-accounts-api.service';
import { OrgSettings, SettingsApiService } from '../settings/settings-api.service';
import {
  AudienceFilter,
  Campaign,
  CampaignsApiService,
  TemplateVariableBinding,
} from './campaigns-api.service';
import {
  TemplateCategory,
  TemplateChannel,
  TemplateExternalStatus,
  TemplateListQuery,
  TemplateRead,
  TemplatesApiService,
} from '../templates/templates-api.service';
import { TemplateStatusBadgeComponent } from '../templates/template-status-badge.component';
import { HtmlComposerComponent } from '../templates/editor/html-composer.component';

/**
 * Step 15 — local picker row. Both the WhatsApp and non-WhatsApp
 * branches feed into this shape so the rest of the modal compiles
 * unchanged after the central-library swap. Body lives on `body`
 * (mapped from the central row's ``body_text``); WA's ``{{n}}``
 * positional placeholders are detected from this same field.
 *
 * Campaigns v1 Step 01 — carry `category`, `language`, and
 * `externalStatus` so the picker can render badges + a subtitle line
 * and disable non-approved WA rows without another lookup.
 */
interface PickerRow {
  id: string;
  name: string;
  body: string;
  channel: ConversationChannel;
  subject: string | null;
  category: TemplateCategory;
  language: string;
  externalStatus: TemplateExternalStatus;
  /** Campaigns v1 Step 02 — Meta's rejection text on WhatsApp rows,
   *  fed into the status badge's hover tooltip so the operator sees
   *  why a template can't be selected without leaving the CRM. */
  externalRejectionReason: string | null;
}

function toPickerRow(row: TemplateRead): PickerRow {
  return {
    id: row.id,
    name: row.name,
    body: row.body_text,
    channel: row.channel as ConversationChannel,
    subject: row.subject,
    category: row.category,
    language: row.language,
    externalStatus: row.external_status,
    externalRejectionReason: row.external_rejection_reason,
  };
}

const CATEGORY_LABEL: Record<TemplateCategory, string> = {
  marketing: 'Marketing',
  transactional: 'Transactional',
  service: 'Service',
};

/** Step 15 — the campaign channel set includes ``'web'`` for the
 *  embedded web widget; the central template library doesn't carry
 *  web templates. The `_loadTemplates` path short-circuits for any
 *  channel not in this set, leaving the operator with the free-text
 *  fallback. Push templates exist in the library (Step 13) but
 *  aren't a campaign channel yet; they re-enter this set when push
 *  send transport ships. */
const _TEMPLATE_CHANNELS: ReadonlySet<ConversationChannel> = new Set<ConversationChannel>([
  'whatsapp',
  'email',
  'sms',
  'facebook',
  'instagram',
]);

/**
 * Create-campaign modal.
 *
 * Two template authoring modes drive the body input:
 *
 *  - **Free text** (non-WA channels, or WA-text-fallback): textarea
 *    with `{{full_name}}` Mustache placeholder for the legacy
 *    contact-name interpolation.
 *  - **WA template picker** (Step 3.5.5 — channel='whatsapp'):
 *    dropdown of approved templates loaded from
 *    `GET /api/v1/integrations/whatsapp/templates?status=APPROVED`.
 *    Selecting a template shows a body preview + one input per
 *    `{{n}}` placeholder; each input has a "Static text" / "Contact
 *    field" toggle so the operator can either pin a literal value
 *    or bind to a contact attribute (full_name / phone / email).
 *    Step 3.5.6 dispatch resolves the field bindings per contact.
 *
 * Schema-level validation (backend `CampaignCreate`) enforces
 * "exactly one of template or template_id" — this modal serializes
 * the right shape based on the selected mode.
 */
@Component({
  selector: 'app-create-campaign-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    LucideAngularModule,
    SendFromPickerComponent,
    AbTestSectionComponent,
    TemplateStatusBadgeComponent,
    HtmlComposerComponent,
  ],
  templateUrl: './create-campaign-modal.component.html',
})
export class CreateCampaignModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(CampaignsApiService);
  private readonly integrationsApi = inject(IntegrationsApiService);
  private readonly templatesApi = inject(TemplatesApiService);
  private readonly groupsApi = inject(ContactGroupsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly emailAccountsApi = inject(EmailAccountsApiService);
  private readonly settingsApi = inject(SettingsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Output() readonly created = new EventEmitter<Campaign>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  // --- Audience builder state (Step 3.5.9) --------------------------

  /** Three modes — Everyone (default), Saved group, Custom filter.
   *  Per Step 3.5.9 pre-implementation choice (a) — "Everyone" is
   *  the safest default for a fresh campaign. */
  protected readonly audienceMode = signal<'everyone' | 'group' | 'filter'>('everyone');
  protected readonly groups = signal<ContactGroup[]>([]);
  protected readonly groupsLoaded = signal(false);
  protected readonly selectedGroupId = signal<string | null>(null);

  protected readonly audienceCount = signal<number | null>(null);
  protected readonly audienceCountLoading = signal(false);
  private readonly audiencePreview$ = new Subject<void>();

  /** Live preview of the first page of contacts matching the current
   *  Custom-filter inputs. Populated only in filter mode so the
   *  operator can visually confirm who they're targeting before
   *  scheduling. */
  protected readonly audiencePreviewRows = signal<ContactListItem[]>([]);
  protected readonly audiencePreviewLoading = signal(false);
  /** Preview page size. Kept small — the list is a visual sanity
   *  check, not a full paginated table. */
  private readonly AUDIENCE_PREVIEW_LIMIT = 20;

  /** Collapsed state for the Matching-contacts panel. Once the
   *  operator has finished picking contacts they can click "Hide" to
   *  free up vertical space — the selected chip strip stays visible
   *  so the choice is still obvious. Manual-only toggle: typing a
   *  new search doesn't force it back open, mirroring the shopping-
   *  cart pattern (checkout continues to work with the drawer closed). */
  protected readonly audiencePreviewCollapsed = signal(false);

  protected toggleAudiencePreviewCollapsed(): void {
    this.audiencePreviewCollapsed.update((v) => !v);
  }

  /** Contacts the operator has hand-picked from the preview list.
   *  Stored as a Map (id → ContactListItem) so the chip strip can
   *  render each picked contact's name even after the preview
   *  refreshes with a different search. Non-empty = the campaign is
   *  scoped to exactly these ids at save time (overrides q/source/tag).
   *  Empty = "use the filter as-is", i.e. dynamic resolution at
   *  dispatch. */
  protected readonly selectedContactMap = signal<Map<string, ContactListItem>>(new Map());

  /** Derived: array view of the selection for template iteration. */
  protected readonly selectedContactList = computed<ContactListItem[]>(() =>
    Array.from(this.selectedContactMap().values()),
  );

  protected isContactSelected(id: string): boolean {
    return this.selectedContactMap().has(id);
  }

  protected toggleContactSelected(c: ContactListItem): void {
    const next = new Map(this.selectedContactMap());
    if (next.has(c.id)) next.delete(c.id);
    else next.set(c.id, c);
    this.selectedContactMap.set(next);
  }

  protected removeSelectedContact(id: string): void {
    const next = new Map(this.selectedContactMap());
    next.delete(id);
    this.selectedContactMap.set(next);
  }

  protected selectAllShown(): void {
    const next = new Map(this.selectedContactMap());
    for (const c of this.audiencePreviewRows()) next.set(c.id, c);
    this.selectedContactMap.set(next);
  }

  protected clearSelection(): void {
    this.selectedContactMap.set(new Map());
  }

  // --- WhatsApp send capacity state (Step 3.5.16) --------------------

  /** Signal mirror of `form.controls.channel.value` so the capacity-
   *  warning `computed()` blocks below react to channel changes
   *  (form controls aren't signals on their own). Synced via the
   *  valueChanges subscription in the constructor. */
  protected readonly channelSignal = signal<ConversationChannel>('whatsapp');

  /** `null` = not yet loaded or WhatsApp not connected (409). The
   *  banner is hidden in both cases — the user sees no error, and
   *  the existing "no approved templates" empty state already
   *  signals the disconnected branch. */
  protected readonly capacity = signal<WhatsAppCapacity | null>(null);
  protected readonly capacityLoading = signal(false);

  // --- Central template picker state (Step 15) ---------------------

  /** Templates available for the currently-selected channel. Loaded
   *  from the central library — `GET /api/v1/templates?channel=…
   *  &internal_status=published(&external_status=approved for WA)`.
   *  Replaces the legacy WA-only integrations endpoint. */
  protected readonly templates = signal<PickerRow[]>([]);

  /** Per-channel cache so toggling channels doesn't refetch. Cleared
   *  only if the modal is re-mounted. */
  private readonly templatesCache = new Map<ConversationChannel, PickerRow[]>();

  /** Slim id+name projection for the A/B section's template dropdowns.
   *  WhatsApp: only offer approved templates. Since Step 01 broadened
   *  the picker query to include pending/rejected rows (so users see
   *  status inline), the A/B dropdowns must re-filter — the server
   *  would reject a pending/rejected variant anyway. */
  protected approvedTemplatesForPicker(): Array<{
    id: string;
    name: string;
  }> {
    return this.templates()
      .filter((t) => (t.channel === 'whatsapp' ? t.externalStatus === 'approved' : true))
      .map((t) => ({ id: t.id, name: t.name }));
  }

  /** WA picker row is selectable only when Meta has approved it.
   *  Non-WA channels have no external review — every published row
   *  is selectable. */
  protected isRowSelectable(row: PickerRow): boolean {
    if (row.channel !== 'whatsapp') return true;
    return row.externalStatus === 'approved';
  }

  /** Subtitle line under the template name: `Category · lang · body preview`.
   *  Body clipped to ~80 chars so long templates don't blow the row height. */
  protected rowSubtitle(row: PickerRow): string {
    const category = CATEGORY_LABEL[row.category] ?? row.category;
    const preview = (row.body ?? '').replace(/\s+/g, ' ').trim();
    const clipped = preview.length > 80 ? preview.slice(0, 77) + '…' : preview;
    const language = row.language || '—';
    return clipped ? `${category} · ${language} · ${clipped}` : `${category} · ${language}`;
  }

  /** Click handler for a picker row. Non-selectable rows (pending /
   *  rejected WA) are a hard no-op — no selection change, no error.
   *  Clicking the currently-selected template toggles it off so the
   *  operator can back out to "no template" and edit the body inline
   *  without having to pick a different one first. */
  protected onRowClick(row: PickerRow): void {
    if (!this.isRowSelectable(row)) return;
    if (this.selectedTemplateId() === row.id) {
      this.selectedTemplateId.set(null);
      return;
    }
    this.selectedTemplateId.set(row.id);
  }
  protected readonly templatesLoading = signal(false);
  protected readonly templatesLoaded = signal(false);
  protected readonly selectedTemplateId = signal<string | null>(null);
  /** Variable bindings per `{{n}}`. Key is the variable number as
   *  string ('1','2',...) to match backend's JSONB shape. Only
   *  populated for WhatsApp templates (Meta's positional HSM shape).
   *  Other channels use named `{{contact.first_name}}` variables that
   *  the dispatcher resolves per-contact at send time — no operator
   *  bindings to capture. */
  protected readonly variables = signal<Record<string, TemplateVariableBinding>>({});

  protected readonly contactFieldOptions: ReadonlyArray<{
    value: string;
    label: string;
  }> = [
    { value: 'full_name', label: 'Contact full name' },
    { value: 'phone', label: 'Contact phone' },
    { value: 'email', label: 'Contact email' },
  ];

  // --- Campaigns v1 Step 03 — Email sender identity state -----------

  /** Verified (`sync_state === 'live'`) mailboxes the org has connected.
   *  Fetched lazily the first time the channel switches to Email so
   *  WhatsApp-only orgs never pay the roundtrip. `null` = not fetched
   *  yet; `[]` = fetched and org has zero verified accounts (drives the
   *  empty-state banner in the template). */
  protected readonly emailAccounts = signal<EmailAccount[] | null>(null);
  protected readonly emailAccountsLoading = signal(false);

  /** Campaigns v1 Step 07c — proactive CAN-SPAM check. Populated on
   *  first Email-channel flip; ``false`` here means the operator hasn't
   *  set Store Profile → address_line1, which will hard-block Start.
   *  Rendered as a red banner with a link to Settings → Store Profile
   *  so they can fix it without reading a raw 400 later. */
  protected readonly orgSettings = signal<OrgSettings | null>(null);
  protected readonly orgSettingsLoading = signal(false);
  protected readonly orgAddressMissing = computed<boolean>(() => {
    const s = this.orgSettings();
    if (s === null) return false; // unknown → don't scare the user
    return !(s.address_line1 && s.address_line1.trim().length > 0);
  });

  /** Merge tags the operator can insert into the Subject line via the
   *  "Insert variable ▾" affordance. Named-variable syntax matching the
   *  dispatcher's per-contact resolution path. */
  protected readonly subjectMergeTags: ReadonlyArray<{ value: string; label: string }> = [
    { value: '{{first_name}}', label: 'First name' },
    { value: '{{full_name}}', label: 'Full name' },
    { value: '{{email}}', label: 'Email' },
  ];
  /** Bound as a component property because Angular's template parser
   *  would otherwise mis-interpret the ``{{`` in the placeholder as a
   *  binding expression. */
  protected readonly subjectPlaceholder = 'Your monthly deals, {{first_name}} 🎁';

  protected readonly selectedTemplate = computed<PickerRow | null>(
    () => this.templates().find((t) => t.id === this.selectedTemplateId()) ?? null,
  );

  protected readonly templateVariableNumbers = computed<number[]>(() => {
    const t = this.selectedTemplate();
    if (!t) return [];
    // Match the backend's _VARIABLE_RE — distinct, sorted. Empty for
    // non-WA templates (they use named variables, not positional).
    const found = new Set<number>();
    const re = /\{\{(\d+)\}\}/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(t.body)) !== null) {
      found.add(parseInt(m[1], 10));
    }
    return [...found].sort((a, b) => a - b);
  });

  // --- form ---------------------------------------------------------

  protected readonly varFullName = '{{full_name}}';
  protected readonly varPhone = '{{phone}}';
  protected readonly templatePlaceholder =
    'Hi {{full_name}} — our Diwali sale is live! 20% off everything this week.';

  /** Campaigns v1 scope locked to WhatsApp + Email (memory
   *  ``project_campaigns_scope.md``). Legacy campaigns on other
   *  channels still render on the list page; the create flow just
   *  doesn't offer them so a user can't start a broken one. */
  protected readonly channels: ReadonlyArray<{
    value: ConversationChannel;
    label: string;
  }> = [
    { value: 'whatsapp', label: 'WhatsApp' },
    { value: 'email', label: 'Email' },
  ];

  protected readonly form = this.fb.group({
    name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    channel: this.fb.control<ConversationChannel>('whatsapp', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    audience_q: this.fb.control<string | null>(null),
    audience_source: this.fb.control<string | null>(null),
    audience_tag: this.fb.control<string | null>(null),
    // Free-text body — required ONLY when no template is selected for
    // a WA campaign, OR for any non-WA channel. The submit handler
    // does the conditional check rather than dynamic Validators.
    template: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.maxLength(4096)],
    }),
    schedule_at: this.fb.control<string | null>(null),
    // Step 27b — multi-number Send-From selector. Null = use org
    // default. The dropdown self-hides when the org has < 2
    // connected phones (the SendFromPickerComponent enforces that
    // at render time).
    send_from_phone_id: this.fb.control<string | null>(null),
    // Step 29 — A/B testing knobs. `is_ab_test` is the master
    // gate; the section component reads the other four fields.
    is_ab_test: this.fb.control<boolean>(false, { nonNullable: true }),
    variant_a_template_id: this.fb.control<string | null>(null),
    variant_b_template_id: this.fb.control<string | null>(null),
    split_ratio: this.fb.control<number>(50, { nonNullable: true }),
    winner_metric: this.fb.control<'reply_rate' | 'read_rate' | 'click_rate' | null>(null),
    winner_holdback_hours: this.fb.control<number>(24, {
      nonNullable: true,
    }),
    // Campaigns v1 Step 03 — Email sender identity + subject + preheader.
    // Every control below is nullable so WhatsApp submits stay clean.
    // Required-when-Email is enforced in `save()` before we hit the
    // API, and the backend echoes the same check with a 422.
    email_account_id: this.fb.control<string | null>(null),
    sender_name: this.fb.control<string | null>(null, [Validators.maxLength(120)]),
    reply_to: this.fb.control<string | null>(null, [Validators.email, Validators.maxLength(320)]),
    subject: this.fb.control<string | null>(null, [Validators.maxLength(998)]),
    preheader: this.fb.control<string | null>(null, [Validators.maxLength(200)]),
    // Campaigns v1 Step 04 — inline HTML body for Email campaigns that
    // don't reference a template. Mutually exclusive with `template`
    // and the picker; the save handler picks one source of truth
    // before calling the API.
    body_html: this.fb.control<string>('', [Validators.maxLength(200000)]),
  });

  constructor() {
    // Mirror the three Email-branch form fields into `emailBranchState`
    // so `emailBranchIncomplete` (a signal-computed) re-evaluates on
    // every keystroke / dropdown pick. Reactive-forms `valueChanges`
    // is what actually notifies us — the signal is just the bridge to
    // Angular signal reactivity.
    const _pushEmailBranchState = () => {
      const v = this.form.getRawValue();
      this.emailBranchState.set({
        email_account_id: v.email_account_id ?? null,
        sender_name: v.sender_name ?? '',
        subject: v.subject ?? '',
      });
    };
    this.form.controls.email_account_id.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(_pushEmailBranchState);
    this.form.controls.sender_name.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(_pushEmailBranchState);
    this.form.controls.subject.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(_pushEmailBranchState);

    // Step 15 — load templates whenever the channel changes. Each
    // channel's published templates come from the central library;
    // the picker reset clears any stale selection from the prior
    // channel so the operator doesn't accidentally submit an
    // out-of-channel template_id.
    this.form.controls.channel.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((channel) => {
        this.channelSignal.set(channel);
        this.selectedTemplateId.set(null);
        this._loadTemplates(channel);
        if (channel === 'whatsapp' && this.capacity() === null) {
          this._loadCapacity();
        }
        // Campaigns v1 Step 03 — lazy-fetch verified mailboxes the
        // first time the operator picks Email. When they switch away,
        // clear the mailbox selection so the payload never carries a
        // stale email_account_id on a WA campaign.
        if (channel === 'email') {
          if (this.emailAccounts() === null) {
            this._loadEmailAccounts();
          }
          if (this.orgSettings() === null) {
            this._loadOrgSettings();
          }
          // A/B testing + Send-From are WhatsApp-only knobs. Clear any
          // toggle the operator left on before flipping to Email so the
          // payload doesn't carry `is_ab_test: true` into an Email
          // campaign that has no variant selector rendered.
          this.form.patchValue({
            send_from_phone_id: null,
            is_ab_test: false,
            variant_a_template_id: null,
            variant_b_template_id: null,
            winner_metric: null,
          });
        } else {
          this.form.patchValue({
            email_account_id: null,
            sender_name: null,
            reply_to: null,
            subject: null,
            preheader: null,
            // Campaigns v1 Step 04 — HTML body is Email-only; drop any
            // stale HTML when the operator flips away.
            body_html: '',
          });
        }
      });

    // Initial load — default channel is whatsapp.
    this._loadTemplates(this.form.controls.channel.value);
    if (this.form.controls.channel.value === 'whatsapp') {
      this._loadCapacity();
    }

    // Load saved groups once for the audience builder dropdown.
    this._loadGroups();

    // Audience-size preview — debounced, runs on mode/filter/group changes.
    this.audiencePreview$
      .pipe(
        debounceTime(300),
        switchMap(() => this._currentAudiencePreviewObservable()),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((count) => {
        this.audienceCount.set(count);
        this.audienceCountLoading.set(false);
      });

    // Contact-row preview — same debounced trigger, populated only
    // in Custom-filter mode so the operator can eyeball the target set.
    this.audiencePreview$
      .pipe(
        debounceTime(300),
        switchMap(() => this._currentAudiencePreviewRowsObservable()),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((rows) => {
        this.audiencePreviewRows.set(rows);
        this.audiencePreviewLoading.set(false);
      });

    // Recompute audience preview whenever any of the audience inputs
    // change. The mode signal + filter form controls all feed in.
    effect(() => {
      // tracks audienceMode + selectedGroupId
      this.audienceMode();
      this.selectedGroupId();
      this.audiencePreview$.next();
    });
    this.form.controls.audience_q.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.audiencePreview$.next());
    this.form.controls.audience_source.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.audiencePreview$.next());
    this.form.controls.audience_tag.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.audiencePreview$.next());

    // Reset variable bindings whenever the selected template changes
    // — pre-fill each `{{n}}` with an empty static binding.
    effect(() => {
      const nums = this.templateVariableNumbers();
      if (this.selectedTemplate() === null) {
        this.variables.set({});
        return;
      }
      const next: Record<string, TemplateVariableBinding> = {};
      for (const n of nums) {
        next[String(n)] = { kind: 'static', value: '' };
      }
      this.variables.set(next);
    });
  }

  /** WhatsApp branch gate. Reads through ``channelSignal`` so the
   *  ``@if (isWhatsAppChannel())`` guards + capacity banner re-render
   *  the moment the operator flips the channel — matches the
   *  Email-side pattern below. */
  protected isWhatsAppChannel(): boolean {
    return this.channelSignal() === 'whatsapp';
  }

  /** Campaigns v1 Step 03 — Email branch gate for the modal's
   *  conditional field render + submit disable. Mirrors the
   *  `channel === 'email'` check but reads through channelSignal so
   *  computed()s can subscribe. */
  protected isEmailChannel(): boolean {
    return this.channelSignal() === 'email';
  }

  /** Insert a merge tag at the end of the subject value. A future
   *  polish step could preserve caret position; end-of-string is the
   *  standard fallback most builders offer. */
  protected onInsertSubjectTag(token: string): void {
    const ctrl = this.form.controls.subject;
    const current = ctrl.value ?? '';
    ctrl.setValue(current + token);
    ctrl.markAsDirty();
  }

  /** Bridge for the <app-html-composer>'s (valueChange) — the composer
   *  is a plain input/output component (no ControlValueAccessor) so the
   *  modal owns the form-control writes. */
  protected onEmailBodyHtmlChange(html: string): void {
    this.form.controls.body_html.setValue(html);
    this.form.controls.body_html.markAsDirty();
  }

  /** Signal mirror of the three Email-branch form fields so the
   *  `emailBranchIncomplete` computed re-evaluates when the operator
   *  types in Sender name / Subject or picks a mailbox. Without this,
   *  the computed reads `form.getRawValue()` — which isn't a signal —
   *  so Angular never invalidates the cache and Save Draft stays
   *  disabled even when every field is filled. */
  protected readonly emailBranchState = signal<{
    email_account_id: string | null;
    sender_name: string;
    subject: string;
  }>({
    email_account_id: null,
    sender_name: '',
    subject: '',
  });

  /** True when the Email branch is missing any of its required fields.
   *  Drives the disabled state on the submit button so the operator
   *  can't send a payload the backend would 422. */
  protected readonly emailBranchIncomplete = computed<boolean>(() => {
    if (!this.isEmailChannel()) return false;
    const v = this.emailBranchState();
    return (
      !v.email_account_id ||
      !(v.sender_name && v.sender_name.trim()) ||
      !(v.subject && v.subject.trim())
    );
  });

  private _loadEmailAccounts(): void {
    this.emailAccountsLoading.set(true);
    this.emailAccountsApi
      .listVerified()
      .pipe(
        catchError(() => of<EmailAccount[]>([])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((rows) => {
        this.emailAccounts.set(rows);
        this.emailAccountsLoading.set(false);
        // Auto-pick the mailbox when the operator has exactly one
        // verified account. Removes a form-control sync bug where the
        // `<select>` visually shows the option but the reactive form
        // never captures it, leaving `email_account_id` null and the
        // Save Draft button disabled with an "Pick a mailbox…" tooltip.
        if (rows.length === 1 && !this.form.controls.email_account_id.value) {
          this.form.controls.email_account_id.setValue(rows[0].id);
          this.form.controls.email_account_id.markAsDirty();
        }
      });
  }

  private _loadOrgSettings(): void {
    this.orgSettingsLoading.set(true);
    this.settingsApi
      .get()
      .pipe(
        catchError(() => of<OrgSettings | null>(null)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((row) => {
        this.orgSettings.set(row);
        this.orgSettingsLoading.set(false);
      });
  }

  protected onAudienceModeChange(mode: 'everyone' | 'group' | 'filter'): void {
    this.audienceMode.set(mode);
    if (mode !== 'group') {
      this.selectedGroupId.set(null);
    }
    if (mode !== 'filter') {
      this.form.patchValue({
        audience_q: null,
        audience_source: null,
        audience_tag: null,
      });
      this.clearSelection();
    }
  }

  protected onSelectedGroupChange(groupId: string): void {
    this.selectedGroupId.set(groupId || null);
  }

  private _loadGroups(): void {
    this.groupsApi
      .list(1, 100)
      .pipe(
        catchError(() => of({ items: [], total: 0, page: 1, size: 0 })),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((response) => {
        this.groups.set(response.items);
        this.groupsLoaded.set(true);
      });
  }

  private _currentAudiencePreviewObservable() {
    const mode = this.audienceMode();
    if (mode === 'everyone') {
      // "Everyone" = empty filter. The preview-size endpoint rejects
      // both-empty payloads, so we skip the call and show null.
      this.audienceCountLoading.set(false);
      return of(null);
    }
    if (mode === 'group') {
      const gid = this.selectedGroupId();
      if (!gid) {
        this.audienceCountLoading.set(false);
        return of(null);
      }
      this.audienceCountLoading.set(true);
      return this.groupsApi.previewSize({ group_id: gid }).pipe(
        switchMap((r) => of(r.count)),
        catchError(() => of(null)),
      );
    }
    // filter mode — call shape uses `GroupFilter` (the
    // preview-size endpoint is owned by the groups API and only
    // accepts q/source/tag; `group_id` belongs to the campaign-side
    // AudienceFilter shape, not the preview request).
    const filter: GroupFilter = {};
    const v = this.form.getRawValue();
    if (v.audience_q?.trim()) filter.q = v.audience_q.trim();
    if (v.audience_source?.trim()) filter.source = v.audience_source.trim();
    if (v.audience_tag?.trim()) filter.tag = v.audience_tag.trim();
    if (!filter.q && !filter.source && !filter.tag) {
      this.audienceCountLoading.set(false);
      return of(null);
    }
    this.audienceCountLoading.set(true);
    return this.groupsApi.previewSize({ filter_json: filter }).pipe(
      switchMap((r) => of(r.count)),
      catchError(() => of(null)),
    );
  }

  /** Rows companion to the count observable. Only Custom-filter mode
   *  fetches — Everyone and Saved-group modes clear the list.
   *  Sends q/source/tag through the contacts list endpoint (same
   *  filters the audience count uses) and takes a small page. */
  private _currentAudiencePreviewRowsObservable() {
    const mode = this.audienceMode();
    if (mode !== 'filter') {
      this.audiencePreviewLoading.set(false);
      return of<ContactListItem[]>([]);
    }
    const v = this.form.getRawValue();
    const q = v.audience_q?.trim() || undefined;
    const source = v.audience_source?.trim() || undefined;
    const tag = v.audience_tag?.trim() || undefined;
    if (!q && !source && !tag) {
      this.audiencePreviewLoading.set(false);
      return of<ContactListItem[]>([]);
    }
    this.audiencePreviewLoading.set(true);
    return this.contactsApi
      .list({ q, source, tag, page: 1, size: this.AUDIENCE_PREVIEW_LIMIT })
      .pipe(
        switchMap((resp) => of(resp.items)),
        catchError(() => of<ContactListItem[]>([])),
      );
  }

  protected onTemplateChange(templateId: string): void {
    this.selectedTemplateId.set(templateId || null);
  }

  protected onVariableKindChange(varNum: number, kind: 'static' | 'field'): void {
    const current = this.variables();
    const key = String(varNum);
    const existing = current[key] ?? { kind: 'static', value: '' };
    this.variables.set({
      ...current,
      [key]: {
        kind,
        // Switching mode clears the value so the operator picks fresh.
        value: existing.kind === kind ? existing.value : '',
      },
    });
  }

  protected onVariableValueChange(varNum: number, value: string): void {
    const current = this.variables();
    const key = String(varNum);
    const existing = current[key] ?? { kind: 'static', value: '' };
    this.variables.set({
      ...current,
      [key]: { kind: existing.kind, value },
    });
  }

  /** Step 15 — channel-aware central-library load. Campaigns v1 Step 01
   *  broadened the WhatsApp query: instead of pre-filtering to
   *  `external_status=approved`, we now fetch every published WA
   *  template (approved, pending, rejected) so the picker can show
   *  status + rejection reason inline and the operator understands
   *  why a template can't be selected. Non-approved rows render
   *  disabled — see `isRowSelectable`. */
  private _loadTemplates(channel: ConversationChannel): void {
    const cached = this.templatesCache.get(channel);
    if (cached) {
      this.templates.set(cached);
      this.templatesLoaded.set(true);
      this.templatesLoading.set(false);
      return;
    }
    this.templatesLoading.set(true);
    this.templatesLoaded.set(false);
    this.templates.set([]);
    // The campaign channel set includes 'web' for the widget; the
    // central library doesn't carry web templates (push covers that
    // surface — Step 13). For 'web' the picker just returns no rows,
    // and the operator falls through to the free-text body.
    if (!_TEMPLATE_CHANNELS.has(channel)) {
      this.templatesLoading.set(false);
      this.templatesLoaded.set(true);
      this.templates.set([]);
      return;
    }
    const filter: TemplateListQuery = {
      channel: channel as TemplateChannel,
      internal_status: 'published',
      limit: 200,
    };
    this.templatesApi
      .list(filter)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          const rows: PickerRow[] = res.items.map((row) => toPickerRow(row));
          this.templatesCache.set(channel, rows);
          this.templates.set(rows);
          this.templatesLoaded.set(true);
          this.templatesLoading.set(false);
        },
        error: () => {
          this.templatesLoading.set(false);
          this.templatesLoaded.set(true);
          this.templates.set([]);
          // Don't block the modal on template load failure — operator
          // can still use the free-text fallback.
        },
      });
  }

  private _loadCapacity(): void {
    this.capacityLoading.set(true);
    this.integrationsApi
      .getWhatsAppCapacity()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (c) => {
          this.capacity.set(c);
          this.capacityLoading.set(false);
        },
        error: () => {
          // 409 (WhatsApp not connected) and any transient error fall
          // through to the same null state — the banner stays hidden
          // and the existing "no templates" empty state already tells
          // the operator to connect WhatsApp.
          this.capacity.set(null);
          this.capacityLoading.set(false);
        },
      });
  }

  /** Refresh the capacity banner — bound to the banner's "Refresh"
   *  button. Re-fetches even when the previous load succeeded. */
  protected refreshCapacity(): void {
    this._loadCapacity();
  }

  /** Coloured-band hint for the banner. `null` when capacity isn't
   *  loaded yet or WhatsApp isn't connected. */
  protected readonly capacityBand = computed<'green' | 'amber' | 'red' | null>(() => {
    const c = this.capacity();
    if (!c || c.is_unlimited) return null;
    if (c.usage_percent >= 90) return 'red';
    if (c.usage_percent >= 70) return 'amber';
    return 'green';
  });

  /** Banner severity for the audience-vs-quota cross-check. `error`
   *  when the selected audience exceeds remaining quota; `warning`
   *  when it would consume >50% of remaining. `null` otherwise. */
  protected readonly audienceQuotaWarning = computed<{
    kind: 'error' | 'warning';
    message: string;
  } | null>(() => {
    const c = this.capacity();
    if (!c || c.is_unlimited) return null;
    if (this.channelSignal() !== 'whatsapp') return null;
    const pickedSize = this.selectedContactMap().size;
    const count = pickedSize > 0 ? pickedSize : this.audienceCount();
    if (count === null || count <= 0) return null;
    if (count > c.remaining) {
      const skipped = count - c.remaining;
      return {
        kind: 'error',
        message: `${count.toLocaleString()} contacts selected, but only ${c.remaining.toLocaleString()} sends remaining today. ${skipped.toLocaleString()} will be skipped or queue for tomorrow.`,
      };
    }
    if (c.remaining > 0 && count > c.remaining * 0.5) {
      const pct = Math.round((count / c.remaining) * 100);
      return {
        kind: 'warning',
        message: `This campaign will use ${pct}% of today's remaining quota.`,
      };
    }
    return null;
  });

  /** Send button gate — disables the submit when WhatsApp quota is
   *  exhausted. Non-WhatsApp channels are never gated. */
  protected readonly quotaBlocksSubmit = computed<boolean>(() => {
    const c = this.capacity();
    if (!c) return false;
    if (c.is_unlimited) return false;
    if (this.channelSignal() !== 'whatsapp') return false;
    return c.remaining === 0;
  });

  protected save(): void {
    if (!this.form.valid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    // Audience serialization is mode-driven (Step 3.5.9):
    //   - everyone → empty object (backend interprets as "all contacts")
    //   - group    → { group_id }
    //   - filter   → { q?, source?, tag? } (only fields with values)
    // Mixing modes is impossible by construction here, and the
    // backend's AudienceFilter validator double-checks.
    const audience: AudienceFilter = {};
    const mode = this.audienceMode();
    if (mode === 'group') {
      const gid = this.selectedGroupId();
      if (!gid) {
        this.submitError.set('Pick a saved group, or switch to a different audience mode.');
        return;
      }
      audience.group_id = gid;
    } else if (mode === 'filter') {
      const picked = Array.from(this.selectedContactMap().keys());
      if (picked.length > 0) {
        // Explicit selection wins over q/source/tag — send goes to
        // exactly the ticked contacts.
        audience.contact_ids = picked;
      } else {
        if (v.audience_q?.trim()) audience.q = v.audience_q.trim();
        if (v.audience_source?.trim()) audience.source = v.audience_source.trim();
        if (v.audience_tag?.trim()) audience.tag = v.audience_tag.trim();
      }
    }
    // 'everyone' mode leaves `audience` as {} — backend treats as
    // "all org contacts" (already the existing default behaviour).

    // Step 15 — decide template vs template_id mode. Any channel with
    // a selected template_id sends through the central library; the
    // free-text fallback fires only when no template is picked.
    const useTemplatePicker = this.selectedTemplateId() !== null;
    // Campaigns v1 Step 04 — inline HTML body is Email-only and
    // mutually exclusive with the picker + free-text textarea. If the
    // operator authored HTML, that's the source of truth; we clear the
    // plain `template` value in the payload below so the backend's
    // exactly-one-source guard is satisfied.
    const emailInlineHtml = v.channel === 'email' ? (v.body_html?.trim() ?? '') : '';
    const useInlineHtml = emailInlineHtml.length > 0;

    if (useTemplatePicker) {
      // WA's positional `{{n}}` placeholders require operator-supplied
      // bindings before the dispatcher can render per-contact. Named
      // variables on other channels resolve automatically from the
      // contact row — no bindings to validate.
      const bindings = this.variables();
      for (const n of this.templateVariableNumbers()) {
        const b = bindings[String(n)];
        if (!b || !b.value.trim()) {
          this.submitError.set(`Fill in a value for variable {{${n}}}.`);
          return;
        }
      }
    } else if (!useInlineHtml && !v.template.trim()) {
      this.submitError.set('Provide a message body or pick a template.');
      return;
    }

    // Campaigns v1 Step 03 — Email required-field guard. Backend
    // enforces the same invariant; catching it client-side keeps the
    // error inline instead of round-tripping a 422.
    if (v.channel === 'email') {
      const missing: string[] = [];
      if (!v.email_account_id) missing.push('a sender mailbox');
      if (!(v.sender_name && v.sender_name.trim())) missing.push('a sender name');
      if (!(v.subject && v.subject.trim())) missing.push('a subject');
      if (missing.length) {
        this.submitError.set(`Email campaigns need ${missing.join(', ')}.`);
        return;
      }
    }

    this.submitting.set(true);
    this.submitError.set(null);
    this.api
      .create({
        name: v.name,
        channel: v.channel,
        audience_filter: audience,
        // Backend's exactly-one-source guard requires exactly one of
        // template / template_id / body_html — pick per the resolved
        // mode above.
        template: useTemplatePicker || useInlineHtml ? null : v.template,
        template_id: useTemplatePicker ? this.selectedTemplateId() : null,
        template_variables: useTemplatePicker ? this.variables() : null,
        schedule_at: v.schedule_at ? new Date(v.schedule_at).toISOString() : null,
        // Step 27b — null on single-number orgs (picker hidden);
        // when set, the dispatcher pins the campaign to this
        // specific WhatsApp phone instead of the org default.
        send_from_phone_id: v.send_from_phone_id ?? null,
        // Step 29 — A/B test config. Server defaults take over
        // when is_ab_test is false; the variant pair + metric are
        // required otherwise (server validates).
        is_ab_test: v.is_ab_test ?? false,
        variant_a_template_id: v.is_ab_test ? (v.variant_a_template_id ?? null) : null,
        variant_b_template_id: v.is_ab_test ? (v.variant_b_template_id ?? null) : null,
        split_ratio: v.split_ratio ?? 50,
        winner_metric: v.is_ab_test ? (v.winner_metric ?? null) : null,
        winner_holdback_hours: v.winner_holdback_hours ?? 24,
        // Campaigns v1 Step 03 — Email sender identity + subject + preheader.
        // Null on non-Email channels so backend + DB row stay clean.
        email_account_id: v.channel === 'email' ? (v.email_account_id ?? null) : null,
        sender_name: v.channel === 'email' ? (v.sender_name ?? null) : null,
        reply_to: v.channel === 'email' ? (v.reply_to ?? null) : null,
        subject: v.channel === 'email' ? (v.subject ?? null) : null,
        preheader: v.channel === 'email' ? (v.preheader ?? null) : null,
        // Campaigns v1 Step 04 — inline HTML body. Only sent when the
        // operator authored HTML for an Email campaign; every other
        // combination stays null so the exactly-one-source guard is
        // satisfied.
        body_html: useInlineHtml ? emailInlineHtml : null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (campaign) => {
          this.submitting.set(false);
          this.created.emit(campaign);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Could not create campaign.');
        },
      });
  }

  protected close(): void {
    this.cancel.emit();
  }
}

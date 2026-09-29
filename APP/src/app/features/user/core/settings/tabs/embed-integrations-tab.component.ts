import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { deriveApiOrigin } from '@core/services/url.util';
import { environment } from '../../../../../../environments/environment';
import {
  AvailableCustomField,
  EmbedApiService,
  EmbedKey,
  WidgetConfigBranding,
  WidgetConfigDocument,
  WidgetConfigField,
  WidgetConfigSpamProtection,
  WidgetConfigUpdatePayload,
  WidgetFormListItem,
} from './embed-api.service';
import { IssueKeyModalComponent } from './issue-key-modal.component';
import { SubmissionLogComponent } from './submission-log.component';
import { ConfirmDialogComponent } from '../../shared/confirm-dialog/confirm-dialog.component';

/** Map a contact-custom-field type to the widget field_type the
 *  renderer knows about. Backend `_WIDGET_SUPPORTED_CUSTOM_TYPES`
 *  already filters out anything not in this set. */
function customTypeToWidgetType(t: string): WidgetConfigField['field_type'] {
  switch (t) {
    case 'email':
      return 'email';
    case 'phone':
      return 'tel';
    case 'number':
      return 'number';
    case 'date':
      return 'date';
    case 'select':
      return 'select';
    default:
      return 'text';
  }
}

/**
 * Settings → Embed Widget tab. Three panels stacked vertically:
 *
 *   1. **Keys** — table of issued keys with Issue / Revoke. Modal
 *      handles the one-time-display of the plaintext secret.
 *   2. **Form configuration** — editable field list, button label,
 *      thank-you copy, branding. Save button PUTs the whole config.
 *   3. **Install snippet** — the `<div>` + `<script>` to paste on
 *      the customer's website, pre-filled with their most recent
 *      live key.
 *
 * Three independent signals (`keys`, `config`, `dirty`) drive each
 * panel. The "Save" button on Panel 2 stays disabled until the
 * config is `dirty` (any field changed since last load/save).
 */
@Component({
  selector: 'app-settings-embed-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LucideAngularModule,
    IssueKeyModalComponent,
    SubmissionLogComponent,
    ConfirmDialogComponent,
  ],
  templateUrl: './embed-integrations-tab.component.html',
})
export class EmbedIntegrationsTabComponent {
  private readonly api = inject(EmbedApiService);
  private readonly destroyRef = inject(DestroyRef);

  // Tab strip — toggle between Keys & Config (default) and the
  // Submission log. State is component-local; deep-linking to a
  // specific tab is a follow-on if Owners ask for it.
  protected readonly activeTab = signal<'config' | 'log'>('config');

  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saving = signal(false);
  protected readonly saveError = signal<string | null>(null);
  protected readonly saveOkAt = signal<number | null>(null);

  // --- Multi-form (Step 8) — Forms toolbar state -----------------------

  /** Every live form the org owns. Populated on load; refreshed after
   *  create / set-default / delete. */
  protected readonly forms = signal<WidgetFormListItem[]>([]);

  /** The form the config editor + keys table are scoped to. Starts on
   *  the org's default form; the operator switches with the top strip. */
  protected readonly selectedFormId = signal<string | null>(null);

  /** Derived row for the toolbar header (name + slug + is_default). */
  protected readonly selectedForm = computed<WidgetFormListItem | null>(
    () => this.forms().find((f) => f.id === this.selectedFormId()) ?? null,
  );

  /** True when the org has more than one live form — hides the
   *  "delete" button on the last remaining form (backend also 422s
   *  this, but the UI polish is nicer if the button just isn't there). */
  protected readonly hasMultipleForms = computed(() => this.forms().length > 1);

  /** Inline "New form" state — a simple name input rendered above the
   *  toolbar when open. Kept in-tab (no dedicated modal component) so
   *  Step 8 stays small; a proper modal is a nice future polish. */
  protected readonly newFormOpen = signal(false);
  protected readonly newFormName = signal('');
  protected readonly newFormSaving = signal(false);
  protected readonly newFormError = signal<string | null>(null);

  /** Guard for confusable UI states — save/delete/set-default all
   *  briefly disable the toolbar while their request is in flight. */
  protected readonly toolbarBusy = signal(false);

  /** Delete-form confirm dialog state. Non-null while open. */
  protected readonly deleteFormConfirm = signal<{
    form: WidgetFormListItem;
    submitting: boolean;
    error: string | null;
  } | null>(null);

  /** Rename-form modal state. Held here (not on the form row) so a
   *  refresh via ``reload()`` doesn't tear down the modal mid-edit.
   *  The rename modal is a small dedicated overlay with a text input,
   *  distinct from the confirm-dialog which is body-text-only. */
  protected readonly renameFormState = signal<{
    form: WidgetFormListItem;
    name: string;

    submitting: boolean;
    error: string | null;
  } | null>(null);

  // --- Panel 1: keys ----------------------------------------------------
  protected readonly keys = signal<EmbedKey[]>([]);
  protected readonly issueModalOpen = signal(false);
  protected readonly revokingId = signal<string | null>(null);
  /** In-flight guard for the two-step revoke → remove flow. */
  protected readonly purgingId = signal<string | null>(null);

  /** Confirm-dialog state for revoke / remove. Uses the shared
   *  ``app-confirm-dialog`` so the messaging + button styling match
   *  the rest of the CRM (contacts, leads, walk-ins) instead of the
   *  native ``window.confirm`` prompt. Null when closed; otherwise
   *  holds the key + action being confirmed. */
  protected readonly keyConfirm = signal<{
    action: 'revoke' | 'purge';
    key: EmbedKey;
    error: string | null;
  } | null>(null);

  /** True when an in-flight submit is happening for the confirmed
   *  action — drives the dialog's disabled state. */
  protected readonly keyConfirmSubmitting = computed(() => {
    const c = this.keyConfirm();
    if (!c) return false;
    return c.action === 'revoke' ? this.revokingId() === c.key.id : this.purgingId() === c.key.id;
  });

  /** Most-recent live key for the CURRENTLY-SELECTED form, used to
   *  pre-fill the install snippet. `listKeys(formId)` already scopes
   *  the fetch to this form, so we just pick the newest live row. */
  protected readonly activeKey = computed<EmbedKey | null>(() => {
    const live = this.keys().filter((k) => !k.revoked_at);
    return live.length > 0 ? live[0] : null;
  });

  // --- Panel 2: config (editable copy of the loaded doc) ---------------
  protected readonly config = signal<WidgetConfigDocument | null>(null);
  protected readonly dirty = signal(false);

  // Contact custom fields the Owner can opt IN to the widget. Lazily
  // loaded the first time the picker is opened (most Settings visits
  // won't touch custom fields, so we avoid the extra request).
  protected readonly availableCustomFields = signal<AvailableCustomField[] | null>(null);
  protected readonly pickerOpen = signal(false);
  protected readonly pickerLoading = signal(false);
  protected readonly pickerError = signal<string | null>(null);

  /** Subset of `availableCustomFields` not already in the config. The
   *  picker filters these out so the same field can't be added twice.
   *  Filter key is `${entity}.${field_key}` so a contact `address`
   *  and a lead `address` (if both exist) don't shadow each other. */
  protected readonly pickerOptions = computed<AvailableCustomField[]>(() => {
    const all = this.availableCustomFields() ?? [];
    const cfg = this.config();
    if (!cfg) return all;
    const exposed = new Set(
      cfg.fields.filter((f) => f.field_source === 'custom').map((f) => `${f.entity}.${f.key}`),
    );
    return all.filter((f) => !exposed.has(`${f.entity}.${f.field_key}`));
  });

  // --- Panel 3: install snippet ----------------------------------------
  protected readonly snippetCopied = signal(false);

  protected readonly snippet = computed<string>(() => {
    const key = this.activeKey();
    if (!key) return '';
    const form = this.selectedForm();
    // Multi-form Step 9: the widget JS bundle honours ``data-form`` on
    // the script tag to load the right form's config. Non-default forms
    // MUST supply it; the default form works without it too but we
    // include it uniformly so operators don't have to remember which
    // one is default.
    const dataForm = form ? ` data-form="${form.slug}"` : '';
    // ``data-host`` points the widget's config + submit calls at THIS
    // instance's API. Without it the widget falls back to the
    // ``DEFAULT_HOST`` baked into the bundle at build time.
    return (
      '<div id="crm-form"></div>\n' +
      `<script src="${environment.embedWidgetHost}/v1/widget.js" ` +
      `data-key="${key.prefix}…"${dataForm} data-host="${deriveApiOrigin()}"></script>`
    );
  });

  constructor() {
    this.reload();
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    // Multi-form: load the forms list first, then pick the default
    // (or the current selection when the operator is refreshing after
    // an edit) as the scope for the config + keys panels below.
    this.api
      .listForms()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.forms.set(rows);
          const desired = this.selectedFormId();
          const picked =
            (desired ? rows.find((f) => f.id === desired) : null) ??
            rows.find((f) => f.is_default) ??
            rows[0] ??
            null;
          this.selectedFormId.set(picked ? picked.id : null);
          if (picked) {
            this._loadFormAndKeys(picked.id);
          } else {
            // Fresh org with no forms yet — the config-service
            // ``get_or_create`` lazy-seeds a default form on first
            // ``GET /embed/config``, so hit that once and then
            // re-list forms to pick it up.
            this._bootstrapDefaultForm();
          }
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load forms.');
        },
      });
  }

  /** Called after the operator switches which form the editor is
   *  scoped to (or after a successful save/create/set-default). Loads
   *  the form's full config + its embed keys in parallel. */
  private _loadFormAndKeys(formId: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listKeys(formId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.keys.set(rows),
        error: (err: HttpErrorResponse) =>
          this.loadError.set(extractApiError(err) ?? 'Could not load keys.'),
      });
    this.api
      .getForm(formId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (form) => {
          this.config.set(form.config);
          this.dirty.set(false);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load form config.');
        },
      });
  }

  /** No-forms case: hit the legacy ``GET /embed/config`` which lazy-
   *  seeds the org's default form, then re-run ``reload()`` to pick
   *  it up. Runs at most once per empty-org load. */
  private _bootstrapDefaultForm(): void {
    this.api
      .getConfig()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.reload(),
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not create default form.');
        },
      });
  }

  // --- Panel 1 handlers ------------------------------------------------

  protected openIssueModal(): void {
    this.issueModalOpen.set(true);
  }

  protected onModalClosed(): void {
    this.issueModalOpen.set(false);
    const formId = this.selectedFormId();
    if (!formId) return;
    // Multi-form Step 8: rescope the key list to the currently
    // selected form so a newly-issued key shows up on this form's
    // panel (issued keys are always pinned to a form via the modal).
    this.api
      .listKeys(formId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((rows) => this.keys.set(rows));
  }

  protected revoke(key: EmbedKey): void {
    if (key.revoked_at) return;
    // Open the shared confirm dialog instead of a native ``confirm``
    // so the messaging + styling match the rest of the CRM. The
    // ``(confirm)`` handler on the dialog dispatches the actual API
    // call via ``executeKeyConfirm``.
    this.keyConfirm.set({ action: 'revoke', key, error: null });
  }

  /** Two-step-flow "remove from list" — only valid on revoked keys.
   *  The backend enforces the same rule (422 ``must_revoke_first``)
   *  so the button is defensive UX rather than authoritative. */
  protected purge(key: EmbedKey): void {
    if (!key.revoked_at) return;
    if (this.purgingId() === key.id) return;
    this.keyConfirm.set({ action: 'purge', key, error: null });
  }

  /** Confirm-dialog labels — derived from the pending action so the
   *  template stays declarative. `keyConfirm()` is non-null exactly
   *  when the dialog is open. */
  protected keyConfirmTitle(): string {
    const c = this.keyConfirm();
    if (!c) return '';
    const label = c.key.name ? `"${c.key.name}"` : `prefix ${c.key.prefix}`;
    return c.action === 'revoke' ? `Revoke key ${label}?` : `Remove key ${label}?`;
  }

  protected keyConfirmBody(): string {
    const c = this.keyConfirm();
    if (!c) return '';
    return c.action === 'revoke'
      ? 'Any sites using this key will stop working immediately. The key stays visible in the list until you remove it.'
      : "This permanently deletes the key from the list. Can't be undone — but since it's already revoked, no live site is affected.";
  }

  protected keyConfirmButton(): string {
    return this.keyConfirm()?.action === 'purge' ? 'Remove' : 'Revoke';
  }

  /** Fired by the shared confirm-dialog's ``(confirm)`` output.
   *  Dispatches to the right API call based on the pending action. */
  protected executeKeyConfirm(): void {
    const c = this.keyConfirm();
    if (!c) return;
    if (c.action === 'revoke') this._doRevoke(c.key);
    else this._doPurge(c.key);
  }

  protected cancelKeyConfirm(): void {
    if (this.keyConfirmSubmitting()) return;
    this.keyConfirm.set(null);
  }

  private _doRevoke(key: EmbedKey): void {
    this.revokingId.set(key.id);
    this.api
      .revokeKey(key.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.revokingId.set(null);
          this.keys.update((rows) =>
            rows.map((r) => (r.id === key.id ? { ...r, revoked_at: new Date().toISOString() } : r)),
          );
          this.keyConfirm.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.revokingId.set(null);
          this.keyConfirm.update((prev) =>
            prev ? { ...prev, error: extractApiError(err) ?? 'Could not revoke key.' } : prev,
          );
        },
      });
  }

  private _doPurge(key: EmbedKey): void {
    this.purgingId.set(key.id);
    this.api
      .purgeKey(key.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.purgingId.set(null);
          this.keys.update((rows) => rows.filter((r) => r.id !== key.id));
          this.keyConfirm.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.purgingId.set(null);
          this.keyConfirm.update((prev) =>
            prev ? { ...prev, error: extractApiError(err) ?? 'Could not remove key.' } : prev,
          );
        },
      });
  }

  protected keyStatusBadge(key: EmbedKey): { label: string; cls: string } {
    if (key.revoked_at) {
      return {
        label: 'Revoked',
        cls: 'bg-surface-2 text-muted border-subtle',
      };
    }
    return {
      label: 'Active',
      cls: 'bg-emerald-100 text-emerald-700 ring-emerald-200',
    };
  }

  protected relativeTime(iso: string | null): string {
    if (!iso) return 'never';
    const ms = Date.now() - new Date(iso).getTime();
    const minutes = Math.floor(ms / 60_000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  }

  // --- Panel 2 handlers ------------------------------------------------

  /** Mutate the field at `index` immutably + mark dirty. */
  private updateField(index: number, patch: Partial<WidgetConfigField>): void {
    const cur = this.config();
    if (!cur) return;
    const next = {
      ...cur,
      fields: cur.fields.map((f, i) => (i === index ? { ...f, ...patch } : f)),
    };
    this.config.set(next);
    this.dirty.set(true);
  }

  protected onFieldLabelInput(index: number, event: Event): void {
    this.updateField(index, {
      label: (event.target as HTMLInputElement).value,
    });
  }

  protected onFieldPlaceholderInput(index: number, event: Event): void {
    this.updateField(index, {
      placeholder: (event.target as HTMLInputElement).value || null,
    });
  }

  protected onFieldRequiredToggle(index: number, event: Event): void {
    this.updateField(index, {
      required: (event.target as HTMLInputElement).checked,
    });
  }

  /** Remove a field from the widget. Standard fields stay defined on the
   *  contact (Settings → Custom fields); they just stop appearing on the
   *  widget. Custom fields likewise. Reversible by re-adding. */
  protected removeField(index: number): void {
    const cur = this.config();
    if (!cur) return;
    const next = {
      ...cur,
      fields: cur.fields
        .filter((_, i) => i !== index)
        // Re-pack `order` so the remaining fields are 0..n-1; the backend
        // doesn't care, but consistent ordering avoids gaps in the UI.
        .map((f, i) => ({ ...f, order: i })),
    };
    this.config.set(next);
    this.dirty.set(true);
  }

  // --- "Add custom field" picker --------------------------------------

  protected openPicker(): void {
    this.pickerOpen.set(true);
    if (this.availableCustomFields() !== null) return;
    this.pickerLoading.set(true);
    this.pickerError.set(null);
    this.api
      .listAvailableCustomFields()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.availableCustomFields.set(rows);
          this.pickerLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.pickerLoading.set(false);
          this.pickerError.set(extractApiError(err) ?? 'Could not load custom fields.');
        },
      });
  }

  protected closePicker(): void {
    this.pickerOpen.set(false);
  }

  protected addCustomField(field: AvailableCustomField): void {
    if (!field.widget_supported) return;
    const cur = this.config();
    if (!cur) return;
    const nextField: WidgetConfigField = {
      key: field.field_key,
      label: field.field_label,
      placeholder: null,
      required: field.is_required,
      order: cur.fields.length,
      field_type: customTypeToWidgetType(field.field_type),
      options: field.options ?? null,
      field_source: 'custom',
      entity: field.entity,
    };
    this.config.set({
      ...cur,
      fields: [...cur.fields, nextField],
    });
    this.dirty.set(true);
  }

  protected moveField(index: number, direction: -1 | 1): void {
    const cur = this.config();
    if (!cur) return;
    const target = index + direction;
    if (target < 0 || target >= cur.fields.length) return;
    const next = { ...cur, fields: [...cur.fields] };
    [next.fields[index], next.fields[target]] = [
      { ...next.fields[target], order: index },
      { ...next.fields[index], order: target },
    ];
    this.config.set(next);
    this.dirty.set(true);
  }

  protected onOptionInput(index: number, event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    const options = raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    this.updateField(index, { options });
  }

  protected interestOptionsValue(): string {
    const cur = this.config();
    if (!cur) return '';
    const interest = cur.fields.find((f) => f.key === 'interest');
    return interest?.options?.join(', ') ?? '';
  }

  /** Index of the `interest` field in the current config, or -1 if
   * the org has removed it. The template uses this to route the
   * comma-separated options input back to the correct field row. */
  protected readonly interestIndex = computed<number>(() => {
    const cur = this.config();
    if (!cur) return -1;
    return cur.fields.findIndex((f) => f.key === 'interest');
  });

  protected onInterestOptionsInput(event: Event): void {
    const idx = this.interestIndex();
    if (idx < 0) return;
    this.onOptionInput(idx, event);
  }

  protected onSubmitLabelInput(event: Event): void {
    const cur = this.config();
    if (!cur) return;
    this.config.set({
      ...cur,
      submit_button_label: (event.target as HTMLInputElement).value,
    });
    this.dirty.set(true);
  }

  protected onThankYouMessageInput(event: Event): void {
    const cur = this.config();
    if (!cur) return;
    this.config.set({
      ...cur,
      thank_you_message: (event.target as HTMLInputElement).value,
    });
    this.dirty.set(true);
  }

  protected onThankYouUrlInput(event: Event): void {
    const cur = this.config();
    if (!cur) return;
    const value = (event.target as HTMLInputElement).value.trim();
    this.config.set({
      ...cur,
      thank_you_url: value || null,
    });
    this.dirty.set(true);
  }

  protected onAccentInput(event: Event): void {
    const cur = this.config();
    if (!cur) return;
    const branding: WidgetConfigBranding = {
      ...cur.branding,
      accent_color: (event.target as HTMLInputElement).value,
    };
    this.config.set({ ...cur, branding });
    this.dirty.set(true);
  }

  protected onLogoUrlInput(event: Event): void {
    const cur = this.config();
    if (!cur) return;
    const value = (event.target as HTMLInputElement).value.trim();
    this.config.set({
      ...cur,
      branding: { ...cur.branding, logo_url: value || null },
    });
    this.dirty.set(true);
  }

  protected onPoweredByToggle(event: Event): void {
    const cur = this.config();
    if (!cur) return;
    this.config.set({
      ...cur,
      branding: {
        ...cur.branding,
        show_powered_by: (event.target as HTMLInputElement).checked,
      },
    });
    this.dirty.set(true);
  }

  // --- Spam protection handlers ---------------------------------------

  /** Apply a partial patch to `spam_protection` immutably + mark dirty. */
  private updateSpam(patch: Partial<WidgetConfigSpamProtection>): void {
    const cur = this.config();
    if (!cur) return;
    this.config.set({
      ...cur,
      spam_protection: { ...cur.spam_protection, ...patch },
    });
    this.dirty.set(true);
  }

  protected onRecaptchaToggle(event: Event): void {
    this.updateSpam({
      recaptcha_enabled: (event.target as HTMLInputElement).checked,
    });
  }

  protected onRecaptchaSiteKeyInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value.trim();
    this.updateSpam({ recaptcha_site_key: value || null });
  }

  protected onRecaptchaSecretKeyInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value.trim();
    this.updateSpam({ recaptcha_secret_key: value || null });
  }

  protected onMinFillTimeInput(event: Event): void {
    const raw = Number((event.target as HTMLInputElement).value);
    const clamped = Number.isFinite(raw) ? Math.min(60_000, Math.max(0, Math.round(raw))) : 2000;
    this.updateSpam({ min_fill_time_ms: clamped });
  }

  protected save(): void {
    const cur = this.config();
    const formId = this.selectedFormId();
    if (!cur || !formId || !this.dirty() || this.saving()) return;
    this.saving.set(true);
    this.saveError.set(null);
    const configPayload: WidgetConfigUpdatePayload = {
      fields: cur.fields,
      submit_button_label: cur.submit_button_label,
      thank_you_message: cur.thank_you_message,
      thank_you_url: cur.thank_you_url ?? null,
      branding: cur.branding,
      spam_protection: cur.spam_protection,
    };
    this.api
      .updateForm(formId, { config: configPayload })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.saving.set(false);
          this.config.set(resp.config);
          this.dirty.set(false);
          this.saveOkAt.set(Date.now());
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.saveError.set(extractApiError(err) ?? 'Could not save form config.');
        },
      });
  }

  // --- Multi-form toolbar handlers -------------------------------------

  /** Switch which form the editor is scoped to. Guards unsaved changes
   *  with a confirm prompt — bailing out preserves the operator's
   *  in-progress edits on the current form. */
  protected onSelectForm(formId: string): void {
    if (formId === this.selectedFormId()) return;
    if (this.dirty() && !confirm('You have unsaved changes. Discard and switch form?')) {
      return;
    }
    this.selectedFormId.set(formId);
    this._loadFormAndKeys(formId);
  }

  protected openNewForm(): void {
    this.newFormName.set('');
    this.newFormError.set(null);
    this.newFormOpen.set(true);
  }

  protected closeNewForm(): void {
    this.newFormOpen.set(false);
  }

  protected onNewFormNameInput(event: Event): void {
    this.newFormName.set((event.target as HTMLInputElement).value);
  }

  protected submitNewForm(): void {
    const name = this.newFormName().trim();
    if (!name || this.newFormSaving()) return;
    this.newFormSaving.set(true);
    this.newFormError.set(null);
    this.api
      .createForm({ name })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (form) => {
          this.newFormSaving.set(false);
          this.newFormOpen.set(false);
          // Switch to the freshly-created form so the operator can
          // start editing its config immediately.
          this.selectedFormId.set(form.id);
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.newFormSaving.set(false);
          this.newFormError.set(extractApiError(err) ?? 'Could not create form.');
        },
      });
  }

  protected setDefault(formId: string): void {
    if (this.toolbarBusy()) return;
    const form = this.forms().find((f) => f.id === formId);
    if (!form || form.is_default) return;
    this.toolbarBusy.set(true);
    this.api
      .setDefaultForm(formId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.toolbarBusy.set(false);
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.toolbarBusy.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not set default form.');
        },
      });
  }

  protected deleteSelectedForm(): void {
    const form = this.selectedForm();
    if (!form || this.toolbarBusy()) return;
    if (form.is_default) return; // Backend also 422s — belt-and-suspenders.
    if (!this.hasMultipleForms()) return;
    // Open the shared styled confirm-dialog. Actual DELETE fires from
    // ``executeDeleteForm`` when the operator clicks Delete.
    this.deleteFormConfirm.set({ form, submitting: false, error: null });
  }

  /** Delete-dialog title / body — as component methods (not inline
   *  template strings) so we can use apostrophes freely without
   *  breaking Angular's expression parser. */
  protected deleteFormTitle(): string {
    const dc = this.deleteFormConfirm();
    return dc ? `Delete form "${dc.form.name}"?` : '';
  }

  protected deleteFormBody(): string {
    return (
      'Every embed key on this form will be revoked — any live snippets on your site ' +
      'stop accepting submissions. Historical leads from this form keep their attribution. ' +
      "This can't be undone."
    );
  }

  protected cancelDeleteForm(): void {
    const c = this.deleteFormConfirm();
    if (!c || c.submitting) return;
    this.deleteFormConfirm.set(null);
  }

  protected executeDeleteForm(): void {
    const c = this.deleteFormConfirm();
    if (!c || c.submitting) return;
    this.deleteFormConfirm.update((prev) =>
      prev ? { ...prev, submitting: true, error: null } : prev,
    );
    this.api
      .deleteForm(c.form.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleteFormConfirm.set(null);
          this.selectedFormId.set(null);
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.deleteFormConfirm.update((prev) =>
            prev
              ? {
                  ...prev,
                  submitting: false,
                  error: extractApiError(err) ?? 'Could not delete form.',
                }
              : prev,
          );
        },
      });
  }

  // --- Rename form (works on any form including the default) -----------

  /** Open the rename modal, prefilled with the form's current name. */
  protected openRenameForm(): void {
    const form = this.selectedForm();
    if (!form || this.toolbarBusy()) return;
    this.renameFormState.set({
      form,
      name: form.name,
      submitting: false,
      error: null,
    });
  }

  protected onRenameNameInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.renameFormState.update((prev) => (prev ? { ...prev, name: value } : prev));
  }

  protected cancelRenameForm(): void {
    const c = this.renameFormState();
    if (!c || c.submitting) return;
    this.renameFormState.set(null);
  }

  protected submitRenameForm(): void {
    const c = this.renameFormState();
    if (!c || c.submitting) return;
    const next = c.name.trim();
    if (!next) return;
    if (next === c.form.name) {
      // No-op rename — just close the modal without a round-trip.
      this.renameFormState.set(null);
      return;
    }
    this.renameFormState.update((prev) =>
      prev ? { ...prev, submitting: true, error: null } : prev,
    );
    this.api
      .updateForm(c.form.id, { name: next })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.renameFormState.set(null);
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.renameFormState.update((prev) =>
            prev
              ? {
                  ...prev,
                  submitting: false,
                  error: extractApiError(err) ?? 'Could not rename form.',
                }
              : prev,
          );
        },
      });
  }

  // --- Panel 3 handlers ------------------------------------------------

  protected async copySnippet(): Promise<void> {
    const text = this.snippet();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      this.snippetCopied.set(true);
      setTimeout(() => this.snippetCopied.set(false), 2000);
    } catch {
      this.snippetCopied.set(false);
    }
  }
}

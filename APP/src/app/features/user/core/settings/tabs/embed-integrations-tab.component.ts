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
} from './embed-api.service';
import { IssueKeyModalComponent } from './issue-key-modal.component';
import { SubmissionLogComponent } from './submission-log.component';

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
  imports: [LucideAngularModule, IssueKeyModalComponent, SubmissionLogComponent],
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

  // --- Panel 1: keys ----------------------------------------------------
  protected readonly keys = signal<EmbedKey[]>([]);
  protected readonly issueModalOpen = signal(false);
  protected readonly revokingId = signal<string | null>(null);

  /** Most-recent live key, used to pre-fill the install snippet. */
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
    return (
      '<div id="furnicrm-form"></div>\n' +
      `<script src="${environment.embedWidgetHost}/v1/widget.js" ` +
      `data-key="${key.prefix}…"></script>`
    );
  });

  constructor() {
    this.reload();
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listKeys()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.keys.set(rows),
        error: (err: HttpErrorResponse) =>
          this.loadError.set(extractApiError(err) ?? 'Could not load keys.'),
      });
    this.api
      .getConfig()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.config.set(resp.config);
          this.dirty.set(false);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load widget config.');
        },
      });
  }

  // --- Panel 1 handlers ------------------------------------------------

  protected openIssueModal(): void {
    this.issueModalOpen.set(true);
  }

  protected onModalClosed(): void {
    this.issueModalOpen.set(false);
    this.api
      .listKeys()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((rows) => this.keys.set(rows));
  }

  protected revoke(key: EmbedKey): void {
    if (key.revoked_at) return;
    const label = key.name ? `"${key.name}"` : `prefix ${key.prefix}`;
    if (!confirm(`Revoke key ${label}? Any sites using it will stop working.`)) return;
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
        },
        error: () => this.revokingId.set(null),
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
    if (!cur || !this.dirty() || this.saving()) return;
    this.saving.set(true);
    this.saveError.set(null);
    const payload: WidgetConfigUpdatePayload = {
      fields: cur.fields,
      submit_button_label: cur.submit_button_label,
      thank_you_message: cur.thank_you_message,
      thank_you_url: cur.thank_you_url ?? null,
      branding: cur.branding,
      spam_protection: cur.spam_protection,
    };
    this.api
      .updateConfig(payload)
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
          this.saveError.set(extractApiError(err) ?? 'Could not save widget config.');
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

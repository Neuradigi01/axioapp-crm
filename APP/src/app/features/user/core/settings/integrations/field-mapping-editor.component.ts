/**
 * Step 8 — Per-subscription field mapping editor.
 *
 * Modal-style component overlaying the Settings page. Opens when an
 * Owner clicks "Edit mapping" on a subscribed form row (Google card
 * exposes the button; Meta uses Page-level subscription so per-form
 * mapping lives here too, just keyed off Meta form fields).
 *
 * Loads three things in parallel on open:
 *   1. CRM mapping targets (`GET /leads/import/targets`) — reused
 *      from the bulk-import surface so dropdowns share one vocab.
 *   2. The subscription row's existing `field_mapping`.
 *   3. The form's actual field list (passed in via input — parent
 *      already fetched via the provider's forms endpoint).
 *
 * Each ad-field row: dropdown of CRM targets (with `(Ignore)` as the
 * default empty option). "Use defaults" applies a small heuristic
 * map (FULL_NAME→full_name, EMAIL→email, PHONE_NUMBER→phone). Save
 * PUTs the full mapping; unknown CRM keys 422 from the backend
 * (surfaced inline).
 *
 * Modal close: clicking the backdrop or Cancel button. Save closes
 * on success.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  IntegrationSubscription,
  IntegrationsApiService,
  MappingTarget,
} from './integrations-api.service';


/** Heuristic defaults applied by the "Use defaults" button. Keys are
 *  compared case-insensitively against ad-field names. The defaults
 *  match what `core.integrations.{google,meta}.tasks._apply_mapping`
 *  expects when the worker maps an inbound payload. */
const DEFAULT_RULES: ReadonlyArray<readonly [RegExp, string]> = [
  [/^full[_ ]?name$/i, 'contact.full_name'],
  [/^name$/i, 'contact.full_name'],
  [/^first[_ ]?name$/i, 'contact.full_name'],
  [/^phone(?:[_ ]?number)?$/i, 'contact.phone'],
  [/^mobile(?:[_ ]?number)?$/i, 'contact.phone'],
  [/^email$/i, 'contact.email'],
  [/^work[_ ]?email$/i, 'contact.email'],
];


@Component({
  selector: 'app-field-mapping-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './field-mapping-editor.component.html',
})
export class FieldMappingEditorComponent {
  /** The subscription being edited. Drives the existing-mapping
   *  load + the PUT-on-save target. */
  readonly subscription = input.required<IntegrationSubscription>();
  /** Ad-platform field names — passed in by the parent which already
   *  fetched the form definition. The dropdowns iterate these. */
  readonly formFields = input.required<ReadonlyArray<string>>();
  /** Human label for the modal header, e.g. "Mumbai Showroom Form". */
  readonly formLabel = input<string | null>(null);

  /** Emitted when the modal should close — backdrop click, Cancel,
   *  or successful save. Parent removes the component from the DOM. */
  readonly closed = output<void>();
  /** Emitted on successful save AFTER `closed` fires so the parent
   *  can refresh its subscriptions list (open editor for the same
   *  sub would otherwise show stale data). */
  readonly saved = output<void>();

  private readonly api = inject(IntegrationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly targets = signal<MappingTarget[]>([]);
  protected readonly mapping = signal<Record<string, string>>({});
  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);

  /** Empty-string sentinel inside the dropdown = "Ignore this field".
   *  We strip those when serialising the PUT body. */
  protected readonly IGNORE = '';

  protected readonly canSave = computed(
    () => !this.loading() && !this.saving(),
  );

  constructor() {
    // First load: when both the subscription and form-fields inputs
    // are set. `effect` is cheap; it'll fire once per input change
    // and bail when already loaded.
    effect(() => {
      const sub = this.subscription();
      const fields = this.formFields();
      if (!sub || !fields) return;
      this._load(sub, fields);
    });
  }

  // --- handlers ----------------------------------------------------

  setTarget(field: string, target: string): void {
    this.mapping.update((m) => ({ ...m, [field]: target }));
  }

  /** Reset every field to the heuristic default (or empty / Ignore
   *  when no rule matches). Doesn't save — the operator confirms
   *  with the Save button. */
  applyDefaults(): void {
    const next: Record<string, string> = {};
    for (const field of this.formFields()) {
      next[field] = this._defaultFor(field);
    }
    this.mapping.set(next);
  }

  save(): void {
    const sub = this.subscription();
    if (!sub) return;
    const filtered = Object.fromEntries(
      Object.entries(this.mapping()).filter(([, v]) => v),
    );
    this.saving.set(true);
    this.error.set(null);
    this.api
      .updateSubscriptionMapping(sub.id, filtered)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.saved.emit();
          this.closed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.error.set(extractApiError(err));
        },
      });
  }

  cancel(): void {
    this.closed.emit();
  }

  /** Backdrop click closes the modal — common modal UX. */
  onBackdrop(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      this.cancel();
    }
  }

  // --- view helpers ------------------------------------------------

  protected groupedTargets = computed(() => {
    const standard: MappingTarget[] = [];
    const custom: MappingTarget[] = [];
    for (const t of this.targets()) {
      (t.custom ? custom : standard).push(t);
    }
    return { standard, custom };
  });

  // --- internals ---------------------------------------------------

  private _load(
    sub: IntegrationSubscription,
    fields: ReadonlyArray<string>,
  ): void {
    this.loading.set(true);
    this.error.set(null);
    forkJoin({
      targets: this.api.listMappingTargets(),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ targets }) => {
          this.targets.set(targets);
          // Seed mapping from existing row; fields not present get
          // the heuristic default (or Ignore).
          const existing = sub.field_mapping ?? {};
          const next: Record<string, string> = {};
          for (const field of fields) {
            next[field] =
              existing[field] !== undefined
                ? existing[field]
                : this._defaultFor(field);
          }
          this.mapping.set(next);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err));
        },
      });
  }

  private _defaultFor(field: string): string {
    for (const [pattern, target] of DEFAULT_RULES) {
      if (pattern.test(field)) return target;
    }
    return '';
  }
}

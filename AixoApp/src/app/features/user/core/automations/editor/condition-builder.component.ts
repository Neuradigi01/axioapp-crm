import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  model,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';
import { catchError, combineLatest, debounceTime, of, switchMap } from 'rxjs';

import {
  AutomationsApiService,
  EnumOption,
  FieldSpec,
  FieldSpecType,
  PreviewMatchesResult,
} from '../automations-api.service';

/**
 * Data-driven condition builder for automation triggers
 * (tasks/automation-conditions/ Step 3).
 *
 * Fed by three inputs:
 *   * `conditions` — two-way AST model; shape locked by the backend
 *     evaluator (`{}` / `{field, op, value}` leaf / `{all: [...]}` /
 *     `{any: [...]}`).
 *   * `conditionFields` — the `FieldSpec[]` for the currently-picked
 *     event, from step-1's extended `/event-types` response. Drives
 *     the field dropdown (grouped, human labels) and picks the
 *     type-appropriate operator set + value input.
 *   * `eventType` — needed to key the field-values cache and to
 *     fire the step-2 `/field-values` endpoint.
 *
 * Each rule renders as three form controls:
 *   1. Field — `<select>` with `<optgroup>` sections keyed by
 *      `FieldSpec.group`, sorted by the `GROUP_ORDER` list below.
 *      Options within a group are alphabetical by `label`.
 *   2. Operator — `<select>` filtered to the ops legal for that
 *      field type. Customer-friendly labels ("Equals" / "At least").
 *   3. Value — type-aware widget:
 *        - enum + single-select op → `<select>` populated by the
 *          live resolver.
 *        - enum + multi-select op (`in` / `not_in`) → tag input
 *          (comma-separated tokens).
 *        - number / currency → `<input type="number">` (currency
 *          shows a ₹ prefix).
 *        - date → `<input type="date">`.
 *        - datetime → `<input type="datetime-local">`.
 *        - boolean → yes/no toggle.
 *        - text → `<input type="text">`.
 *        - Ops that don't need a value (`exists` / `not_exists`)
 *          hide the value input.
 *
 * A sentence preview below the rule list renders the AST in plain
 * English so the customer can eyeball intent before saving.
 *
 * Field-values lookups are cached in-session per component instance;
 * the cache clears when `eventType` changes so switching events
 * doesn't leak stale pools.
 */

type Op =
  | 'eq'
  | 'ne'
  | 'in'
  | 'not_in'
  | 'contains'
  | 'starts_with'
  | 'ends_with'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'exists'
  | 'not_exists'
  | 'regex';

interface Rule {
  field: string;
  op: Op;
  /** String for scalar ops, comma-separated for `in` / `not_in`
   *  before the AST-emit converts it to `string[]`. */
  value: string;
  /** Snapshot of the raw AST leaf this rule was hydrated from —
   *  used for byte-identical round-trip preservation
   *  (tasks/automation-conditions/ Step 4). If the operator never
   *  edits the rule, `emitConditions` returns this original leaf
   *  verbatim, so a legacy trigger's stored JSONB survives a
   *  load-and-save with no drift. Set to `null` on any mutation
   *  (field / op / value change) and on newly-added rules. */
  original: Record<string, unknown> | null;
}

interface OpChoice {
  value: Op;
  label: string;
  /** Preview sentence uses this for readable phrasing
   *  (e.g. "is at least"). Falls back to `label` when unset. */
  sentence?: string;
  needsValue: boolean;
  /** If set, restricts the op to a subset of field types. */
  types?: readonly FieldSpecType[];
}

const OP_CATALOG: readonly OpChoice[] = [
  { value: 'eq', label: 'Equals', sentence: 'equals', needsValue: true },
  { value: 'ne', label: 'Is not', sentence: 'is not', needsValue: true },
  { value: 'in', label: 'Is any of', sentence: 'is any of', needsValue: true },
  { value: 'not_in', label: 'Is not any of', sentence: 'is not any of', needsValue: true },
  {
    value: 'contains',
    label: 'Contains',
    sentence: 'contains',
    needsValue: true,
    types: ['text'],
  },
  {
    value: 'starts_with',
    label: 'Starts with',
    sentence: 'starts with',
    needsValue: true,
    types: ['text'],
  },
  {
    value: 'ends_with',
    label: 'Ends with',
    sentence: 'ends with',
    needsValue: true,
    types: ['text'],
  },
  {
    value: 'gt',
    label: 'Greater than',
    sentence: 'is greater than',
    needsValue: true,
    types: ['number', 'currency', 'date', 'datetime'],
  },
  {
    value: 'gte',
    label: 'At least',
    sentence: 'is at least',
    needsValue: true,
    types: ['number', 'currency', 'date', 'datetime'],
  },
  {
    value: 'lt',
    label: 'Less than',
    sentence: 'is less than',
    needsValue: true,
    types: ['number', 'currency', 'date', 'datetime'],
  },
  {
    value: 'lte',
    label: 'At most',
    sentence: 'is at most',
    needsValue: true,
    types: ['number', 'currency', 'date', 'datetime'],
  },
  { value: 'exists', label: 'Is not empty', sentence: 'is set', needsValue: false },
  { value: 'not_exists', label: 'Is empty', sentence: 'is empty', needsValue: false },
  {
    value: 'regex',
    label: 'Matches regex',
    sentence: 'matches regex',
    needsValue: true,
    types: ['text'],
  },
];

/** Ops legal per field type, in the order they render in the
 *  operator dropdown. `undefined` = the customer-friendly default
 *  list (used for Advanced-mode legacy paths where we don't have a
 *  type). */
const OPS_BY_TYPE: Record<FieldSpecType, readonly Op[]> = {
  text: [
    'eq',
    'ne',
    'contains',
    'starts_with',
    'ends_with',
    'in',
    'not_in',
    'exists',
    'not_exists',
    'regex',
  ],
  number: ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in', 'not_in', 'exists', 'not_exists'],
  currency: ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in', 'not_in', 'exists', 'not_exists'],
  date: ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'exists', 'not_exists'],
  datetime: ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'exists', 'not_exists'],
  boolean: ['eq', 'ne', 'exists', 'not_exists'],
  enum: ['eq', 'ne', 'in', 'not_in', 'exists', 'not_exists'],
};

/** Preferred order of group headers in the field dropdown.
 *  Anything not in this list sorts alphabetically at the end. */
const GROUP_ORDER: readonly string[] = [
  'Contact',
  'Lead',
  'Transition',
  'Appointment',
  'Invoice',
  'Order',
  'Quote',
  'User',
  'Org',
];

interface FieldChoice {
  path: string;
  label: string;
  type: FieldSpecType;
  group: string;
  enum_resolver: string | null;
}

interface GroupedFields {
  group: string;
  options: readonly FieldChoice[];
}

const CURRENCY_SYMBOL = '₹'; // ₹ — India-first CRM per the existing app defaults.

/** Sentinel path for Advanced-mode / legacy rows (custom field path
 *  the customer types by hand). Step-4 auto-selects it when a
 *  loaded trigger references a path not in `conditionFields`. */
const CUSTOM_PATH = '__custom__';

@Component({
  selector: 'app-condition-builder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './condition-builder.component.html',
})
export class ConditionBuilderComponent {
  private readonly api = inject(AutomationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** Caller-supplied AST — two-way bound. */
  readonly conditions = model<Record<string, unknown>>({});

  /** Step-1's field specs for the selected event. Drives the
   *  grouped Field dropdown + type-filtered Op / Value inputs. */
  readonly conditionFields = input<FieldSpec[]>([]);

  /** Selected event's key. Required for cache invalidation +
   *  the live `/field-values` lookups. Empty string ("no event
   *  yet") disables value-pool fetching. */
  readonly eventType = input<string>('');

  /** Sample payload for the selected event. Kept for legacy
   *  Advanced-mode datalist autocomplete only — the primary field
   *  source is `conditionFields`. */
  readonly samplePayload = input<Record<string, unknown>>({});

  readonly disabled = input<boolean>(false);

  protected readonly CURRENCY_SYMBOL = CURRENCY_SYMBOL;
  protected readonly CUSTOM_PATH = CUSTOM_PATH;

  // Local rule list — mirrors the AST. On any change we rebuild the
  // AST and emit via the `conditions` model.
  protected readonly rules = signal<Rule[]>([]);
  protected readonly conjunction = signal<'all' | 'any'>('all');
  protected readonly advancedMode = signal<boolean>(false);

  /** In-session cache of resolved value pools, keyed by
   *  `${eventType}:${fieldPath}`. Cleared when the event changes so
   *  switching from `lead.created` to `contact.created` doesn't
   *  reuse the wrong pipeline stages. Also tracks in-flight fetches
   *  so we don't dispatch the same request twice on rapid re-renders. */
  protected readonly valuePools = signal<Map<string, EnumOption[]>>(new Map());
  private readonly inflightFetches = new Set<string>();

  /** Matched-events preview state (tasks/automation-conditions/
   *  Step 5). `null` before the first fetch fires or after an
   *  error; the loading flag guards the "Checking…" render while
   *  the debounced request is in flight. */
  protected readonly previewResult = signal<PreviewMatchesResult | null>(null);
  protected readonly previewLoading = signal<boolean>(false);
  protected readonly previewError = signal<boolean>(false);

  // --- computed derivatives ------------------------------------

  /** Sorted groups + fields for the `<optgroup>`-rendered dropdown. */
  protected readonly groupedFields = computed<GroupedFields[]>(() => {
    const specs = this.conditionFields();
    if (specs.length === 0) return [];
    const byGroup = new Map<string, FieldChoice[]>();
    for (const spec of specs) {
      const bucket = byGroup.get(spec.group) ?? [];
      bucket.push({
        path: spec.path,
        label: spec.label,
        type: spec.type,
        group: spec.group,
        enum_resolver: spec.enum_resolver,
      });
      byGroup.set(spec.group, bucket);
    }
    const groups = Array.from(byGroup.keys()).sort((a, b) => {
      const ia = GROUP_ORDER.indexOf(a);
      const ib = GROUP_ORDER.indexOf(b);
      if (ia !== -1 && ib !== -1) return ia - ib;
      if (ia !== -1) return -1;
      if (ib !== -1) return 1;
      return a.localeCompare(b);
    });
    return groups.map((group) => ({
      group,
      options: (byGroup.get(group) ?? []).sort((a, b) => a.label.localeCompare(b.label)),
    }));
  });

  /** Path → FieldChoice map for O(1) lookups from the rule row. */
  protected readonly fieldsByPath = computed<Map<string, FieldChoice>>(() => {
    const out = new Map<string, FieldChoice>();
    for (const group of this.groupedFields()) {
      for (const opt of group.options) out.set(opt.path, opt);
    }
    return out;
  });

  /** True when the current field list is empty AND the customer
   *  hasn't turned Advanced on — the builder falls back to a
   *  friendly "not catalogued yet" panel. */
  protected readonly emptyCatalog = computed<boolean>(
    () => this.conditionFields().length === 0 && !this.advancedMode(),
  );

  /** Legacy datalist autocomplete — used only in Advanced-mode rows
   *  where the customer types a raw dot-path. Same flatten as v1. */
  protected readonly fieldSuggestions = computed<string[]>(() => {
    const paths: string[] = [];
    const visit = (node: unknown, prefix: string): void => {
      if (node && typeof node === 'object' && !Array.isArray(node)) {
        for (const [key, value] of Object.entries(node)) {
          const path = prefix ? `${prefix}.${key}` : key;
          paths.push(path);
          if (value && typeof value === 'object' && !Array.isArray(value)) {
            visit(value, path);
          }
        }
      }
    };
    visit(this.samplePayload(), '');
    return paths;
  });

  /** Plain-English preview under the rule list. */
  protected readonly sentencePreview = computed<string>(() => {
    const rs = this.rules();
    if (rs.length === 0) return 'Fires on every matching event.';
    const parts = rs.map((r) => this.rulePhrase(r)).filter((s) => s.length > 0);
    if (parts.length === 0) return 'Fires on every matching event.';
    const joiner = this.conjunction() === 'all' ? ' AND ' : ' OR ';
    return 'Fires when ' + parts.join(joiner) + '.';
  });

  constructor() {
    // Hydrate from the caller's AST on mount.
    this.hydrateFromConditions(this.conditions());

    // Re-parse the AST when the parent re-feeds it (Edit mode
    // loading an existing trigger). Also detects loaded triggers
    // whose paths aren't in the current catalog and auto-engages
    // Advanced mode so the rule stays editable (step-4 territory,
    // but the auto-toggle lands here so the wiring is uniform).
    effect(() => {
      const ast = this.conditions();
      const fields = this.fieldsByPath();
      this.hydrateFromConditions(ast);
      const hasLegacy = this.rules().some((r) => r.field && !fields.has(r.field));
      if (hasLegacy) this.advancedMode.set(true);
    });

    // Event switch → wipe the cached value pools. New event has
    // different fields so old pools are irrelevant.
    effect(() => {
      this.eventType();
      this.valuePools.set(new Map());
      this.inflightFetches.clear();
      // Also invalidate the previous event's preview count — a
      // count from `lead.created` is nonsense once the operator
      // switched to `contact.created`.
      this.previewResult.set(null);
      this.previewError.set(false);
    });

    // Matched-events preview (tasks/automation-conditions/ Step 5).
    // Debounce AST + event-type changes at 500 ms so a fast typer
    // doesn't burn a request per keystroke. Skip when there's no
    // event picked yet (the endpoint would 404) and when the AST
    // has zero rules (a zero-condition trigger fires on every
    // event — showing "would have matched 3 events" for an empty
    // filter would be noise, not signal). Errors are swallowed and
    // surfaced via `previewError` so the render stays subtle
    // ("Preview unavailable") without blocking Save.
    combineLatest([toObservable(this.conditions), toObservable(this.eventType)])
      .pipe(
        debounceTime(500),
        switchMap(([conditions, eventType]) => {
          if (!eventType || !conditions || Object.keys(conditions).length === 0) {
            this.previewResult.set(null);
            this.previewLoading.set(false);
            this.previewError.set(false);
            return of(null);
          }
          this.previewLoading.set(true);
          this.previewError.set(false);
          return this.api.previewMatches(eventType, conditions).pipe(
            catchError(() => {
              this.previewError.set(true);
              this.previewLoading.set(false);
              return of(null);
            }),
          );
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((result) => {
        this.previewLoading.set(false);
        if (result !== null) this.previewResult.set(result);
      });
  }

  // --- rule-level handlers ------------------------------------

  protected addRule(): void {
    if (this.disabled()) return;
    // Default new rules to the first standard field (if any), else
    // to Advanced mode's custom path.
    const first = this.conditionFields()[0];
    const seedField = first?.path ?? '';
    const fresh: Rule = { field: seedField, op: 'eq', value: '', original: null };
    this.rules.update((rs) => [...rs, fresh]);
    if (seedField) this.maybeFetchValues(seedField);
    this.emitConditions();
  }

  protected addAdvancedRule(): void {
    if (this.disabled()) return;
    this.advancedMode.set(true);
    this.rules.update((rs) => [...rs, { field: CUSTOM_PATH, op: 'eq', value: '', original: null }]);
    this.emitConditions();
  }

  protected removeRule(index: number): void {
    if (this.disabled()) return;
    this.rules.update((rs) => rs.filter((_, i) => i !== index));
    this.emitConditions();
  }

  protected onFieldChange(index: number, value: string): void {
    if (this.disabled()) return;
    this.rules.update((rs) =>
      rs.map((r, i) => {
        if (i !== index) return r;
        const next: Rule = { ...r, field: value, original: null };
        // If the new field's type doesn't permit the current op,
        // reset to `eq` so the emitted AST stays valid.
        const type = this.fieldTypeFor(value);
        if (type && !OPS_BY_TYPE[type].includes(r.op)) next.op = 'eq';
        // Enum → clear value so the resolver dropdown starts fresh.
        if (type === 'enum') next.value = '';
        return next;
      }),
    );
    this.maybeFetchValues(value);
    this.emitConditions();
  }

  protected onOpChange(index: number, value: Op): void {
    if (this.disabled()) return;
    this.rules.update((rs) =>
      rs.map((r, i) => {
        if (i !== index) return r;
        const next: Rule = { ...r, op: value, original: null };
        // Op switch that changes the value shape (single ↔ multi
        // select for enum fields) → clear so we don't ship a
        // half-typed value.
        const isMulti = value === 'in' || value === 'not_in';
        const wasMulti = r.op === 'in' || r.op === 'not_in';
        if (isMulti !== wasMulti) next.value = '';
        return next;
      }),
    );
    this.emitConditions();
  }

  protected onValueChange(index: number, value: string): void {
    if (this.disabled()) return;
    this.rules.update((rs) =>
      rs.map((r, i) => (i === index ? { ...r, value, original: null } : r)),
    );
    this.emitConditions();
  }

  protected onTagsChange(index: number, tokens: string[]): void {
    if (this.disabled()) return;
    this.rules.update((rs) =>
      rs.map((r, i) => (i === index ? { ...r, value: tokens.join(','), original: null } : r)),
    );
    this.emitConditions();
  }

  protected onBooleanChange(index: number, value: boolean): void {
    if (this.disabled()) return;
    this.rules.update((rs) =>
      rs.map((r, i) =>
        i === index ? { ...r, value: value ? 'true' : 'false', original: null } : r,
      ),
    );
    this.emitConditions();
  }

  protected toggleConjunction(): void {
    if (this.disabled()) return;
    this.conjunction.update((c) => (c === 'all' ? 'any' : 'all'));
    this.emitConditions();
  }

  protected toggleAdvancedMode(): void {
    this.advancedMode.update((v) => !v);
  }

  // --- per-rule accessors used by the template ----------------

  /** Field type of the rule at `index` — `null` when the rule
   *  references an Advanced / legacy path not in the current
   *  catalog. */
  protected ruleFieldType(index: number): FieldSpecType | null {
    return this.fieldTypeFor(this.rules()[index]?.field ?? '');
  }

  protected ruleIsAdvanced(index: number): boolean {
    const r = this.rules()[index];
    if (!r) return false;
    if (r.field === CUSTOM_PATH) return true;
    // Legacy path — field selected but not in the current catalog.
    return !!r.field && !this.fieldsByPath().has(r.field);
  }

  /** Legacy = rule was hydrated from a stored AST leaf whose field
   *  path isn't in the current catalog. Distinct from Advanced =
   *  operator explicitly added a Custom row via "Add advanced rule"
   *  (which uses the CUSTOM_PATH sentinel). Drives the pill label +
   *  the editor page's deprecation banner. */
  protected ruleIsLegacy(index: number): boolean {
    const r = this.rules()[index];
    if (!r) return false;
    if (r.field === CUSTOM_PATH) return false;
    if (!r.field) return false;
    return !this.fieldsByPath().has(r.field);
  }

  /** Op choices for the rule's field. */
  protected opChoicesFor(index: number): readonly OpChoice[] {
    const type = this.ruleFieldType(index);
    if (type === null) return OP_CATALOG; // Advanced / legacy → all ops
    const allowed = OPS_BY_TYPE[type];
    return OP_CATALOG.filter((c) => allowed.includes(c.value));
  }

  protected opNeedsValue(op: Op): boolean {
    return OP_CATALOG.find((o) => o.value === op)?.needsValue ?? true;
  }

  protected isMultiSelectOp(op: Op): boolean {
    return op === 'in' || op === 'not_in';
  }

  /** Resolved value pool for the rule's field, or `null` when
   *  not-yet-fetched (component shows a "Loading…" placeholder
   *  while `inflightFetches` has the key). Empty array means the
   *  resolver returned zero rows — the customer hasn't set up
   *  the underlying config yet. */
  protected valuePoolFor(rule: Rule): EnumOption[] | null {
    const key = this.cacheKey(rule.field);
    if (!key) return null;
    return this.valuePools().get(key) ?? null;
  }

  /** Resolve a chip's label from the value pool (falls back to the
   *  raw token when the pool isn't loaded / doesn't carry it). */
  protected tokenLabel(rule: Rule, token: string): string {
    const pool = this.valuePoolFor(rule);
    return pool?.find((o) => o.value === token)?.label ?? token;
  }

  /** Chip list for a multi-select enum rule — splits the stored
   *  comma-separated `value` into individual tokens. */
  protected tokensFor(rule: Rule): string[] {
    return rule.value
      ? rule.value
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
      : [];
  }

  protected removeToken(index: number, token: string): void {
    if (this.disabled()) return;
    const next = this.tokensFor(this.rules()[index]).filter((t) => t !== token);
    this.onTagsChange(index, next);
  }

  protected addToken(index: number, token: string): void {
    if (this.disabled()) return;
    const trimmed = token.trim();
    if (!trimmed) return;
    const current = this.tokensFor(this.rules()[index]);
    if (current.includes(trimmed)) return;
    this.onTagsChange(index, [...current, trimmed]);
  }

  // --- value-pool fetch ---------------------------------------

  private maybeFetchValues(fieldPath: string): void {
    const type = this.fieldTypeFor(fieldPath);
    if (type !== 'enum') return;
    const key = this.cacheKey(fieldPath);
    if (!key) return;
    if (this.valuePools().has(key)) return;
    if (this.inflightFetches.has(key)) return;

    this.inflightFetches.add(key);
    this.api
      .listFieldValues(this.eventType(), fieldPath)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (options) => {
          this.inflightFetches.delete(key);
          this.valuePools.update((m) => {
            const next = new Map(m);
            next.set(key, options);
            return next;
          });
        },
        error: () => {
          // Non-fatal — the value dropdown renders the "couldn't
          // load options" hint. Clear the inflight marker so a
          // retry works if the customer re-selects the field.
          this.inflightFetches.delete(key);
          this.valuePools.update((m) => {
            const next = new Map(m);
            next.set(key, []);
            return next;
          });
        },
      });
  }

  private cacheKey(fieldPath: string): string {
    const et = this.eventType();
    if (!et || !fieldPath || fieldPath === CUSTOM_PATH) return '';
    return `${et}:${fieldPath}`;
  }

  private fieldTypeFor(fieldPath: string): FieldSpecType | null {
    return this.fieldsByPath().get(fieldPath)?.type ?? null;
  }

  // --- AST <-> rules conversion -------------------------------

  private hydrateFromConditions(ast: Record<string, unknown>): void {
    if (!ast || Object.keys(ast).length === 0) {
      this.rules.set([]);
      this.conjunction.set('all');
      return;
    }
    if ('all' in ast && Array.isArray(ast['all'])) {
      this.conjunction.set('all');
      this.rules.set(this.parseLeaves(ast['all'] as unknown[]));
      return;
    }
    if ('any' in ast && Array.isArray(ast['any'])) {
      this.conjunction.set('any');
      this.rules.set(this.parseLeaves(ast['any'] as unknown[]));
      return;
    }
    // Single leaf at the root.
    this.conjunction.set('all');
    this.rules.set(this.parseLeaves([ast]));
    // Pre-fetch value pools for every enum rule so switching to the
    // dropdown doesn't blink through a "Loading…" state on first render.
    for (const rule of this.rules()) {
      if (rule.field) this.maybeFetchValues(rule.field);
    }
  }

  private parseLeaves(items: unknown[]): Rule[] {
    const out: Rule[] = [];
    for (const node of items) {
      if (
        node &&
        typeof node === 'object' &&
        'field' in (node as Record<string, unknown>) &&
        'op' in (node as Record<string, unknown>)
      ) {
        const n = node as Record<string, unknown>;
        const value = n['value'];
        out.push({
          field: String(n['field'] ?? ''),
          op: (n['op'] as Op) ?? 'eq',
          value:
            value === undefined
              ? ''
              : typeof value === 'string'
                ? value
                : typeof value === 'boolean'
                  ? String(value)
                  : Array.isArray(value)
                    ? value.join(',')
                    : String(value),
          // Snapshot the raw leaf so an untouched round-trip emits
          // it verbatim — matters most for legacy rules where the
          // stored shape may not match what a re-emit would produce
          // (e.g. numeric value stored as int vs. hydrated as
          // string). Cleared to null on any mutator call.
          original: { ...n },
        });
      }
    }
    return out;
  }

  private emitConditions(): void {
    const rules = this.rules();
    if (rules.length === 0) {
      this.conditions.set({});
      return;
    }
    const leaves = rules.map((r) => this.ruleToLeaf(r));
    if (leaves.length === 1) {
      this.conditions.set(leaves[0]);
      return;
    }
    this.conditions.set({ [this.conjunction()]: leaves });
  }

  private ruleToLeaf(rule: Rule): Record<string, unknown> {
    // Byte-identical round-trip preservation for legacy rules
    // (tasks/automation-conditions/ Step 4). If the rule was
    // hydrated from an AST leaf and the operator hasn't touched it,
    // emit the original leaf verbatim so a save-without-edit
    // produces the same JSONB that was loaded.
    if (rule.original !== null) return { ...rule.original };

    const path = rule.field === CUSTOM_PATH ? '' : rule.field;
    const out: Record<string, unknown> = { field: path.trim(), op: rule.op };
    if (!this.opNeedsValue(rule.op)) return out;
    const v = rule.value;
    if (this.isMultiSelectOp(rule.op)) {
      out['value'] = v
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      return out;
    }
    const type = this.fieldTypeFor(rule.field);
    if (
      type === 'number' ||
      type === 'currency' ||
      rule.op === 'gt' ||
      rule.op === 'gte' ||
      rule.op === 'lt' ||
      rule.op === 'lte'
    ) {
      const num = Number(v);
      out['value'] = Number.isFinite(num) && v !== '' ? num : v;
      return out;
    }
    if (type === 'boolean') {
      out['value'] = v === 'true';
      return out;
    }
    out['value'] = v;
    return out;
  }

  // --- sentence preview helper --------------------------------

  private rulePhrase(rule: Rule): string {
    if (!rule.field) return '';
    const spec = this.fieldsByPath().get(rule.field);
    const opChoice = OP_CATALOG.find((o) => o.value === rule.op);
    const opWord = opChoice?.sentence ?? opChoice?.label ?? rule.op;
    const label = spec ? `${spec.group}'s ${spec.label}` : rule.field;
    if (!opChoice?.needsValue) {
      return `${label} ${opWord}`;
    }
    let valuePhrase: string;
    if (this.isMultiSelectOp(rule.op)) {
      const tokens = this.tokensFor(rule);
      if (tokens.length === 0) return '';
      const pool = this.valuePoolFor(rule);
      const labels = tokens.map((t) => pool?.find((o) => o.value === t)?.label ?? t);
      valuePhrase = labels.map((l) => `"${l}"`).join(', ');
    } else if (spec?.type === 'enum') {
      const pool = this.valuePoolFor(rule);
      const labelled = pool?.find((o) => o.value === rule.value)?.label ?? rule.value;
      valuePhrase = `"${labelled}"`;
    } else if (spec?.type === 'currency') {
      valuePhrase = `${CURRENCY_SYMBOL}${this.formatNumber(rule.value)}`;
    } else if (spec?.type === 'number') {
      valuePhrase = this.formatNumber(rule.value);
    } else if (spec?.type === 'boolean') {
      valuePhrase = rule.value === 'true' ? '"Yes"' : '"No"';
    } else {
      valuePhrase = `"${rule.value}"`;
    }
    return `${label} ${opWord} ${valuePhrase}`;
  }

  private formatNumber(raw: string): string {
    if (!raw) return '0';
    const n = Number(raw);
    if (!Number.isFinite(n)) return raw;
    return n.toLocaleString('en-IN');
  }
}

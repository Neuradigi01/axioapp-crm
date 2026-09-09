import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { FieldDef } from '../shared/dynamic-form/types';
import { FilterClause, FilterDsl, FilterOp, StandardFilterField } from '../shared/filter-dsl.types';

/** UI categories drive the op-picker narrowing — keep this in sync
 * with the backend's `_FIELD_PY_TYPE` in `filter_dsl.py`. */
type ValueKind = 'string' | 'enum' | 'number' | 'date' | 'datetime' | 'uuid' | 'bool';

interface StandardFieldDef {
  field: StandardFilterField;
  label: string;
  kind: ValueKind;
  /** Picklist values when `kind === 'enum'`. */
  choices?: { value: string; label: string }[];
}

/** Standard (non-custom) fields the modal authors. Kept inline because
 * the set is small and stable; if it grows past ~20 entries, extract
 * to a registry the same way module descriptors are wired. */
const STANDARD_FIELDS: StandardFieldDef[] = [
  {
    field: 'status',
    label: 'Status',
    kind: 'enum',
    choices: [
      { value: 'active', label: 'Active' },
      { value: 'won', label: 'Won' },
      { value: 'lost', label: 'Lost' },
    ],
  },
  {
    field: 'source',
    label: 'Source',
    kind: 'enum',
    choices: [
      { value: 'manual', label: 'Manual' },
      { value: 'bulk_import', label: 'Bulk import' },
      // Multi-form track: `widget` enum stays, UI label renders as
      // "Forms" — matches every other lead-source dropdown across
      // the CRM (lead-card badge, campaigns, contact picker).
      { value: 'widget', label: 'Forms' },
      { value: 'google_ads', label: 'Google Ads' },
      { value: 'meta_ads', label: 'Meta Ads' },
      { value: 'whatsapp_flow', label: 'WhatsApp Flow' },
      { value: 'walk_in', label: 'Walk-in' },
    ],
  },
  { field: 'assigned_to_id', label: 'Owner', kind: 'uuid' },
  { field: 'pipeline_stage', label: 'Pipeline stage', kind: 'string' },
  { field: 'lead_score', label: 'Lead score', kind: 'number' },
  { field: 'budget', label: 'Budget', kind: 'number' },
  { field: 'last_activity_at', label: 'Last activity', kind: 'datetime' },
  { field: 'created_at', label: 'Created', kind: 'datetime' },
  { field: 'expected_close_date', label: 'Expected close', kind: 'date' },
  { field: 'contact_name', label: 'Contact name', kind: 'string' },
  { field: 'contact_phone', label: 'Contact phone', kind: 'string' },
  { field: 'contact_email', label: 'Contact email', kind: 'string' },
];

/** Allowed ops per value kind. Matches the backend's accept-set —
 * `contains`/`starts_with` are string-only; `between` doesn't apply to
 * UUIDs; etc. */
const OPS_BY_KIND: Record<ValueKind, FilterOp[]> = {
  string: ['eq', 'neq', 'contains', 'starts_with', 'in', 'nin', 'is_empty', 'is_not_empty'],
  enum: ['eq', 'neq', 'in', 'nin', 'is_empty', 'is_not_empty'],
  number: ['eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'between', 'is_empty', 'is_not_empty'],
  date: ['eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'between', 'is_empty', 'is_not_empty'],
  datetime: ['gt', 'gte', 'lt', 'lte', 'between', 'is_empty', 'is_not_empty'],
  uuid: ['eq', 'neq', 'in', 'nin', 'is_empty', 'is_not_empty'],
  bool: ['eq', 'neq', 'is_empty', 'is_not_empty'],
};

const OP_LABELS: Record<FilterOp, string> = {
  eq: 'equals',
  neq: 'does not equal',
  in: 'is one of',
  nin: 'is not one of',
  gt: 'greater than',
  gte: 'greater than or equal',
  lt: 'less than',
  lte: 'less than or equal',
  contains: 'contains',
  starts_with: 'starts with',
  between: 'between',
  is_empty: 'is empty',
  is_not_empty: 'is not empty',
};

/** Internal row state — what the form binds to. We convert to/from
 * `FilterClause` at the input boundary (`initial`) and the output
 * boundary (`apply`). */
export interface ClauseRow {
  /** Stable id for `@for track`. */
  id: number;
  /** Either a `StandardFilterField` or a `custom_data.<key>` string. */
  field: string;
  op: FilterOp;
  /** Single-value scalar. `between` uses `value` (low) + `valueHi`. */
  value: string;
  /** Upper bound for `between`. */
  valueHi: string;
  /** Comma-separated input for `in`/`nin`; split on apply. */
  valueList: string;
}

@Component({
  selector: 'app-advanced-filter-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, LucideAngularModule],
  templateUrl: './advanced-filter-modal.component.html',
})
export class AdvancedFilterModalComponent {
  /** Pre-existing DSL — hydrate the form so reopening the modal shows
   * the currently active filter. */
  readonly initial = input<FilterDsl | null>(null);

  /** Active custom-field definitions for the org. The modal lets the
   * user filter on `custom_data.<field_key>` for any active def. */
  readonly customFields = input<FieldDef[]>([]);

  readonly apply = output<FilterDsl>();
  readonly cancel = output<void>();

  protected readonly rows = signal<ClauseRow[]>([]);
  /** Strictly increasing id for new rows so `@for track` is stable
   * even after deletes. */
  private nextRowId = 1;

  /** Standard field options for the picker. */
  protected readonly standardFields = STANDARD_FIELDS;

  /** Wrapped for the template (custom field defs). */
  protected readonly customFieldOptions = computed(() =>
    this.customFields()
      .filter((f) => !f.is_hidden)
      .map((f) => ({
        field: `custom_data.${f.field_key}` as const,
        label: f.field_label,
        kind: this.kindForFieldType(f.field_type),
        choices: this.choicesForField(f),
      })),
  );

  constructor() {
    // Rehydrate the form whenever `initial` changes. Tracked once at
    // mount, plus any subsequent input change (e.g. parent rebinds
    // after an "edit existing filter" flow).
    effect(() => {
      const dsl = this.initial();
      this.rehydrate(dsl);
    });
  }

  /** Build the lookup the template uses to render the right value input
   * for a given row. Cheap enough to compute per-call. */
  protected fieldKindFor(field: string): ValueKind {
    const std = STANDARD_FIELDS.find((s) => s.field === field);
    if (std) return std.kind;
    const cust = this.customFieldOptions().find((c) => c.field === field);
    return cust?.kind ?? 'string';
  }

  protected choicesFor(field: string): { value: string; label: string }[] | null {
    const std = STANDARD_FIELDS.find((s) => s.field === field);
    if (std?.choices) return std.choices;
    const cust = this.customFieldOptions().find((c) => c.field === field);
    return cust?.choices ?? null;
  }

  protected opsFor(field: string): FilterOp[] {
    return OPS_BY_KIND[this.fieldKindFor(field)];
  }

  protected opLabel(op: FilterOp): string {
    return OP_LABELS[op];
  }

  /** Does this op carry a single scalar value? (Most do.) */
  protected isScalarOp(op: FilterOp): boolean {
    return ['eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'contains', 'starts_with'].includes(op);
  }

  /** Does this op carry a list value? */
  protected isListOp(op: FilterOp): boolean {
    return op === 'in' || op === 'nin';
  }

  /** Does this op carry a 2-element range? */
  protected isRangeOp(op: FilterOp): boolean {
    return op === 'between';
  }

  /** True for the value-less ops — the value input is hidden. */
  protected isValuelessOp(op: FilterOp): boolean {
    return op === 'is_empty' || op === 'is_not_empty';
  }

  /** What HTML input type to render for a scalar value cell. */
  protected inputTypeFor(field: string): 'text' | 'number' | 'date' | 'datetime-local' {
    const kind = this.fieldKindFor(field);
    if (kind === 'number') return 'number';
    if (kind === 'date') return 'date';
    if (kind === 'datetime') return 'datetime-local';
    return 'text';
  }

  protected onAddRow(): void {
    const defaultField = this.standardFields[0];
    const ops = OPS_BY_KIND[defaultField.kind];
    this.rows.update((rows) => [
      ...rows,
      {
        id: this.nextRowId++,
        field: defaultField.field,
        op: ops[0],
        value: '',
        valueHi: '',
        valueList: '',
      },
    ]);
  }

  protected onRemoveRow(id: number): void {
    this.rows.update((rows) => rows.filter((r) => r.id !== id));
  }

  protected onFieldChange(id: number, newField: string): void {
    this.rows.update((rows) =>
      rows.map((r) => {
        if (r.id !== id) return r;
        const ops = this.opsFor(newField);
        // If the current op isn't valid for the new field type, snap
        // back to the field's first op so the user isn't holding a
        // half-broken row.
        const op = ops.includes(r.op) ? r.op : ops[0];
        return { ...r, field: newField, op, value: '', valueHi: '', valueList: '' };
      }),
    );
  }

  protected onOpChange(id: number, newOp: string): void {
    if (!this.isFilterOp(newOp)) return;
    this.rows.update((rows) => rows.map((r) => (r.id === id ? { ...r, op: newOp } : r)));
  }

  protected onValueChange(id: number, value: string): void {
    this.rows.update((rows) => rows.map((r) => (r.id === id ? { ...r, value } : r)));
  }

  protected onValueHiChange(id: number, valueHi: string): void {
    this.rows.update((rows) => rows.map((r) => (r.id === id ? { ...r, valueHi } : r)));
  }

  protected onValueListChange(id: number, valueList: string): void {
    this.rows.update((rows) => rows.map((r) => (r.id === id ? { ...r, valueList } : r)));
  }

  protected onCancel(): void {
    this.cancel.emit();
  }

  protected onReset(): void {
    this.rows.set([]);
  }

  protected onApply(): void {
    const clauses: FilterClause[] = [];
    for (const row of this.rows()) {
      const clause = this.rowToClause(row);
      if (clause) clauses.push(clause);
    }
    this.apply.emit(clauses.length === 0 ? {} : { all: clauses });
  }

  // --- private helpers ----------------------------------------------------

  private isFilterOp(op: string): op is FilterOp {
    return op in OP_LABELS;
  }

  private kindForFieldType(t: FieldDef['field_type']): ValueKind {
    switch (t) {
      case 'number':
      case 'currency':
        return 'number';
      case 'date':
        return 'date';
      case 'datetime':
        return 'datetime';
      case 'boolean':
        return 'bool';
      default:
        // Text / phone / email / select / multiselect all flow through
        // JSONB ::text on the backend, so they're string-compared.
        return 'string';
    }
  }

  private choicesForField(f: FieldDef): { value: string; label: string }[] | undefined {
    const c = f.options?.choices;
    if (!c?.length) return undefined;
    return c.map((v) => ({ value: v, label: v }));
  }

  /** Convert an authored row into a backend `FilterClause`. Drops rows
   * with empty values (caller doesn't want a half-finished clause to
   * silently broaden the filter). */
  private rowToClause(row: ClauseRow): FilterClause | null {
    const field = row.field as StandardFilterField | `custom_data.${string}`;
    if (this.isValuelessOp(row.op)) {
      return { field, op: row.op };
    }
    if (this.isListOp(row.op)) {
      const items = row.valueList
        .split(',')
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      if (items.length === 0) return null;
      return { field, op: row.op, value: this.coerceList(field, items) };
    }
    if (this.isRangeOp(row.op)) {
      if (!row.value || !row.valueHi) return null;
      return {
        field,
        op: row.op,
        value: [this.coerceScalar(field, row.value), this.coerceScalar(field, row.valueHi)],
      };
    }
    if (row.value === '' || row.value === null) return null;
    return { field, op: row.op, value: this.coerceScalar(field, row.value) };
  }

  /** Best-effort scalar coercion based on the field's kind. The
   * backend re-validates regardless, so we only need to avoid sending
   * a string where a number is expected. */
  private coerceScalar(field: string, raw: string): unknown {
    const kind = this.fieldKindFor(field);
    if (kind === 'number') {
      const n = Number(raw);
      return Number.isFinite(n) ? n : raw;
    }
    if (kind === 'datetime') {
      // <input type="datetime-local"> emits 'YYYY-MM-DDTHH:MM' (no
      // timezone). The backend parses with `datetime.fromisoformat`
      // which treats that as naive UTC — acceptable for v1.
      return raw;
    }
    return raw;
  }

  private coerceList(field: string, items: string[]): unknown[] {
    return items.map((i) => this.coerceScalar(field, i));
  }

  /** Reverse direction: split a `FilterDsl.all` array back into the
   * row shape the form binds to. We ignore `any` for v1 because the
   * UI doesn't author OR groups; reopening a DSL that has `any`
   * clauses still surfaces the `all` ones and leaves the `any` group
   * untouched on Apply (we re-emit only `all`). That's surprising —
   * so we surface a 1-time warning in the console for now and revisit
   * in Step 7 when saved views land. */
  private rehydrate(dsl: FilterDsl | null): void {
    if (!dsl?.all?.length) {
      this.rows.set([]);
      return;
    }
    if (dsl.any?.length) {
      console.warn(
        '[advanced-filter] OR clauses are not editable in v1; they will be replaced on Apply.',
      );
    }
    const next: ClauseRow[] = dsl.all.map((c) => this.clauseToRow(c));
    this.rows.set(next);
  }

  private clauseToRow(c: FilterClause): ClauseRow {
    const id = this.nextRowId++;
    const base: ClauseRow = {
      id,
      field: c.field,
      op: c.op,
      value: '',
      valueHi: '',
      valueList: '',
    };
    if (this.isValuelessOp(c.op)) return base;
    if (this.isListOp(c.op) && Array.isArray(c.value)) {
      return { ...base, valueList: (c.value as unknown[]).map(String).join(', ') };
    }
    if (this.isRangeOp(c.op) && Array.isArray(c.value)) {
      const [lo, hi] = c.value as unknown[];
      return { ...base, value: String(lo ?? ''), valueHi: String(hi ?? '') };
    }
    return { ...base, value: c.value === undefined || c.value === null ? '' : String(c.value) };
  }
}

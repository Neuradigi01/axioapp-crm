import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  model,
  output,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

/**
 * Visual condition builder for automation triggers.
 *
 * Operator adds a list of leaf rules (field/op/value); the
 * component joins them with AND or OR. Output shape matches the
 * backend's condition AST from `core/events/conditions.py`:
 *
 *   - 0 rules: `{}` (always match)
 *   - 1 rule: `{field, op, value}` (the leaf alone)
 *   - 2+ rules: `{all: [<leaves>]}` or `{any: [<leaves>]}`
 *
 * Field-path autocomplete pulls the keys from the selected event's
 * sample_payload (flattened to dot-paths). Operator can still type
 * any path — the backend evaluator handles missing paths as no
 * match.
 *
 * v1 is linear (no nested groups). Drag-drop nested rules are a
 * polish step.
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
  value: string;
}

const OP_OPTIONS: Array<{ value: Op; label: string; needsValue: boolean }> = [
  { value: 'eq', label: '=', needsValue: true },
  { value: 'ne', label: '≠', needsValue: true },
  { value: 'in', label: 'in (comma-separated)', needsValue: true },
  { value: 'not_in', label: 'not in', needsValue: true },
  { value: 'contains', label: 'contains', needsValue: true },
  { value: 'starts_with', label: 'starts with', needsValue: true },
  { value: 'ends_with', label: 'ends with', needsValue: true },
  { value: 'gt', label: '>', needsValue: true },
  { value: 'gte', label: '≥', needsValue: true },
  { value: 'lt', label: '<', needsValue: true },
  { value: 'lte', label: '≤', needsValue: true },
  { value: 'exists', label: 'exists', needsValue: false },
  { value: 'not_exists', label: "doesn't exist", needsValue: false },
  { value: 'regex', label: 'matches regex', needsValue: true },
];

@Component({
  selector: 'app-condition-builder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './condition-builder.component.html',
})
export class ConditionBuilderComponent {
  /** Caller-supplied AST. Two-way bound — the component emits a new
   *  object every time the rule list changes so the parent form can
   *  store it directly. */
  readonly conditions = model<Record<string, unknown>>({});

  /** Sample payload from the selected event's catalog entry —
   *  drives the field-path autocomplete suggestions. */
  readonly samplePayload = input<Record<string, unknown>>({});

  readonly disabled = input<boolean>(false);

  protected readonly OP_OPTIONS = OP_OPTIONS;

  // Local rule list — mirrors the AST. On change → rebuild the
  // AST + emit.
  protected readonly rules = signal<Rule[]>([]);
  protected readonly conjunction = signal<'all' | 'any'>('all');

  // Suggested field paths flattened from the sample payload.
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

  constructor() {
    // Hydrate from the caller's AST on first render + when the
    // input flips.
    this.hydrateFromConditions(this.conditions());
  }

  /** Re-parse the AST when the parent re-feeds it (e.g. on Edit
   *  mode loading an existing trigger). */
  ngOnChanges(): void {
    this.hydrateFromConditions(this.conditions());
  }

  protected addRule(): void {
    if (this.disabled()) return;
    const fresh: Rule = { field: '', op: 'eq', value: '' };
    this.rules.update((rs) => [...rs, fresh]);
    this.emitConditions();
  }

  protected removeRule(index: number): void {
    if (this.disabled()) return;
    this.rules.update((rs) => rs.filter((_, i) => i !== index));
    this.emitConditions();
  }

  protected onFieldChange(index: number, value: string): void {
    this.rules.update((rs) => rs.map((r, i) => (i === index ? { ...r, field: value } : r)));
    this.emitConditions();
  }

  protected onOpChange(index: number, value: Op): void {
    this.rules.update((rs) => rs.map((r, i) => (i === index ? { ...r, op: value } : r)));
    this.emitConditions();
  }

  protected onValueChange(index: number, value: string): void {
    this.rules.update((rs) => rs.map((r, i) => (i === index ? { ...r, value } : r)));
    this.emitConditions();
  }

  protected toggleConjunction(): void {
    this.conjunction.update((c) => (c === 'all' ? 'any' : 'all'));
    this.emitConditions();
  }

  protected opNeedsValue(op: Op): boolean {
    return OP_OPTIONS.find((o) => o.value === op)?.needsValue ?? true;
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
                : Array.isArray(value)
                  ? value.join(',')
                  : JSON.stringify(value),
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
    const out: Record<string, unknown> = {
      field: rule.field.trim(),
      op: rule.op,
    };
    if (!this.opNeedsValue(rule.op)) return out;
    const v = rule.value;
    if (rule.op === 'in' || rule.op === 'not_in') {
      out['value'] = v
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      return out;
    }
    if (rule.op === 'gt' || rule.op === 'gte' || rule.op === 'lt' || rule.op === 'lte') {
      const num = Number(v);
      out['value'] = Number.isFinite(num) ? num : v;
      return out;
    }
    out['value'] = v;
    return out;
  }
}

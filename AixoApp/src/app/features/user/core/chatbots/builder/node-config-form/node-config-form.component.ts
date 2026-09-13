import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { MobileSelectComponent } from '../../../shared/forms/mobile-select.component';
import { BotVariable } from '../../../shared/variable-picker/variable-picker-api.service';
import { VariablePickerComponent } from '../../../shared/variable-picker/variable-picker.component';
import { FieldSchema } from '../node-type-registry';

/**
 * Schema-driven per-node config form. Each node type declares its
 * fields in the registry (`configSchema`) and this component renders
 * them uniformly — no hand-written form per node type.
 *
 * Emits `(patch)` with a *nested* config object shaped like the
 * node's `config`. The parent (builder page) merges it in via
 * `canvas.updateNodeConfig`.
 *
 * Nested keys use dot notation (`header_media.type`) — the read /
 * write helpers walk the object so nested defaults survive.
 */
interface ButtonRow {
  id: string;
  title: string;
}

@Component({
  selector: 'app-node-config-form',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    LucideAngularModule,
    MobileSelectComponent,
    VariablePickerComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './node-config-form.component.html',
})
export class NodeConfigFormComponent {
  @Input({ required: true }) schema: readonly FieldSchema[] = [];
  @Input({ required: true }) config: Record<string, unknown> = {};
  /** When set, `button_list` rows render an inline output port on
   *  the right of the row so operators can wire each button to its
   *  own downstream. Matches Pabbly's inline-port pattern. */
  @Input() nodeId: string | null = null;
  /** Highlight the port whose label matches this — used to show
   *  which port is currently "pending" a connection completion. */
  @Input() pendingPortLabel: string | null = null;
  /** Whether the node this form belongs to is the current
   *  `pendingSourceId` — used with `pendingPortLabel` to highlight. */
  @Input() nodeIsPending = false;
  /** Per-graph session variables — the paths of `answers.<node_id>` from
   *  every Ask-* / Set-Custom-Field node upstream in the current bot.
   *  Injected by the builder page so the variable picker can offer them
   *  alongside the org-wide Contact / Lead / Runtime scopes. */
  @Input() sessionVariables: BotVariable[] = [];

  @Output() readonly patch = new EventEmitter<Record<string, unknown>>();
  @Output() readonly portClick = new EventEmitter<{ label: string; event: MouseEvent }>();

  /** Read a possibly-nested value at `dot.path` from the config. */
  getValue(key: string): unknown {
    const parts = key.split('.');
    let cur: unknown = this.config;
    for (const p of parts) {
      if (cur === null || cur === undefined || typeof cur !== 'object') return undefined;
      cur = (cur as Record<string, unknown>)[p];
    }
    return cur;
  }

  /** Coerce for template `[value]` bindings so undefined doesn't
   *  leak into inputs as the literal string "undefined". */
  getText(key: string): string {
    const v = this.getValue(key);
    return v === null || v === undefined ? '' : String(v);
  }

  getNumber(key: string): number | null {
    const v = this.getValue(key);
    if (v === null || v === undefined || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  getBool(key: string): boolean {
    return !!this.getValue(key);
  }

  getStringList(key: string): string[] {
    const v = this.getValue(key);
    return Array.isArray(v) ? v.map((x) => String(x)) : [];
  }

  getButtonList(key: string): ButtonRow[] {
    const v = this.getValue(key);
    if (!Array.isArray(v)) return [];
    return v.map((row, i) => {
      const r = (row ?? {}) as Record<string, unknown>;
      return {
        id: typeof r['id'] === 'string' ? (r['id'] as string) : `btn_${i + 1}`,
        title: typeof r['title'] === 'string' ? (r['title'] as string) : '',
      };
    });
  }

  /** Rebuild the config with `key` (dot path) replaced by `value` and
   *  emit the whole thing as a patch. Emitting the top-level slice
   *  keeps the merge in `canvas.updateNodeConfig` a plain object
   *  replace — no need to teach the store about deep merge. */
  setValue(key: string, value: unknown): void {
    const parts = key.split('.');
    const next: Record<string, unknown> = this.deepClone(this.config);
    let cur: Record<string, unknown> = next;
    for (let i = 0; i < parts.length - 1; i++) {
      const p = parts[i];
      const existing = cur[p];
      const nested =
        existing && typeof existing === 'object' && !Array.isArray(existing)
          ? (existing as Record<string, unknown>)
          : {};
      cur[p] = nested;
      cur = nested;
    }
    cur[parts[parts.length - 1]] = value;
    this.patch.emit(next);
  }

  onText(key: string, value: string): void {
    this.setValue(key, value);
  }

  /** Insert a `{{path}}` token into a textarea at the caret position
   *  (or at the end if the textarea isn't focused). Preserves any
   *  selected text by replacing it with the token — same behaviour as
   *  HubSpot / Mailchimp merge-tag pickers.
   *
   *  Smart de-dupe: if the operator typed `{{` right before opening the
   *  picker (a natural "I want to insert a variable here" gesture), we
   *  swallow those two chars so the final text is a clean single-token
   *  `{{contact.first_name}}` instead of a broken `{{{{contact.first_name}}`.
   *
   *  Re-focuses the textarea + repositions the caret after the inserted
   *  token so the operator can keep typing without a click. */
  insertToken(textarea: HTMLTextAreaElement, fieldKey: string, token: string): void {
    const value = textarea.value ?? '';
    let start = textarea.selectionStart ?? value.length;
    const end = textarea.selectionEnd ?? value.length;
    // If the two chars immediately before the caret are `{{`, back up
    // and drop them — the token already carries its own leading `{{`.
    if (start === end && start >= 2 && value.slice(start - 2, start) === '{{') {
      start -= 2;
    }
    const nextValue = value.slice(0, start) + token + value.slice(end);
    this.setValue(fieldKey, nextValue);
    // Wait for Angular to flush the value update, then place the caret
    // right after the inserted token so the next keystroke lands there.
    setTimeout(() => {
      textarea.focus();
      const caret = start + token.length;
      textarea.setSelectionRange(caret, caret);
    }, 0);
  }

  onNumber(key: string, raw: string): void {
    if (raw === '' || raw === null || raw === undefined) {
      this.setValue(key, null);
      return;
    }
    const n = Number(raw);
    if (Number.isFinite(n)) this.setValue(key, n);
  }

  onBool(key: string, checked: boolean): void {
    this.setValue(key, checked);
  }

  addStringItem(key: string, raw: string): void {
    const trimmed = (raw ?? '').trim();
    if (!trimmed) return;
    const list = this.getStringList(key);
    if (list.includes(trimmed)) return;
    this.setValue(key, [...list, trimmed]);
  }

  removeStringItem(key: string, idx: number): void {
    const list = this.getStringList(key);
    this.setValue(
      key,
      list.filter((_, i) => i !== idx),
    );
  }

  addButtonItem(key: string, maxItems?: number): void {
    const list = this.getButtonList(key);
    if (maxItems !== undefined && list.length >= maxItems) return;
    const nextId = this.nextButtonId(list);
    this.setValue(key, [...list, { id: nextId, title: `Button ${list.length + 1}` }]);
  }

  removeButtonItem(key: string, idx: number): void {
    const list = this.getButtonList(key);
    this.setValue(
      key,
      list.filter((_, i) => i !== idx),
    );
  }

  updateButtonTitle(key: string, idx: number, title: string): void {
    const list = this.getButtonList(key).map((row, i) =>
      i === idx ? { ...row, title, id: row.id || this.slugify(title, i) } : row,
    );
    this.setValue(key, list);
  }

  updateButtonId(key: string, idx: number, id: string): void {
    const clean = id.trim() || `btn_${idx + 1}`;
    const list = this.getButtonList(key).map((row, i) => (i === idx ? { ...row, id: clean } : row));
    this.setValue(key, list);
  }

  /** JSON field — parse on every keystroke; if it parses, patch;
   *  otherwise swallow the update so the graph stays valid. Errors
   *  render inline. */
  jsonError(key: string): string | null {
    const raw = this.getRawJson(key);
    if (raw === null) return null;
    try {
      JSON.parse(raw);
      return null;
    } catch (e) {
      return e instanceof Error ? e.message : 'Invalid JSON';
    }
  }

  getRawJson(key: string): string | null {
    const v = this.getValue(key);
    if (v === undefined) return '';
    try {
      return JSON.stringify(v, null, 2);
    } catch {
      return '';
    }
  }

  onJson(key: string, raw: string): void {
    try {
      const parsed = raw.trim() === '' ? null : JSON.parse(raw);
      this.setValue(key, parsed);
    } catch {
      // Keep the last-good value; template shows the parse error.
    }
  }

  /** Bubble a button-row port click up to the builder page which
   *  owns the connect state machine. */
  onPortClick(label: string, evt: MouseEvent): void {
    evt.stopPropagation();
    this.portClick.emit({ label, event: evt });
  }

  private nextButtonId(list: ButtonRow[]): string {
    const used = new Set(list.map((b) => b.id));
    for (let i = 1; i < 100; i++) {
      const cand = `btn_${i}`;
      if (!used.has(cand)) return cand;
    }
    return `btn_${Math.random().toString(36).slice(2, 8)}`;
  }

  private slugify(s: string, idx: number): string {
    const base = s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');
    return base || `btn_${idx + 1}`;
  }

  private deepClone<T>(v: T): T {
    return JSON.parse(JSON.stringify(v)) as T;
  }
}

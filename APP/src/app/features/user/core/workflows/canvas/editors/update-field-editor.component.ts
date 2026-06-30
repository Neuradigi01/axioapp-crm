import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CanvasNode } from '../canvas-state.service';

/** Handles all three `record.update_contact` / `record.update_lead` /
 *  `record.update_appointment` types. The dispatcher passes the right
 *  node — entity is inferred from `node.type` and not editable here. */

const VALUE_SOURCES = [
  { value: 'literal', label: 'Literal value' },
  { value: 'trigger_payload', label: 'From trigger payload (dotted path)' },
  { value: 'context', label: 'From run context (dotted path)' },
] as const;

@Component({
  selector: 'app-update-field-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './update-field-editor.component.html',
})
export class UpdateFieldEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly valueSources = VALUE_SOURCES;

  readonly entity = computed<string>(() => {
    const type = this.node().type;
    if (type === 'record.update_contact') return 'contact';
    if (type === 'record.update_lead') return 'lead';
    if (type === 'record.update_appointment') return 'appointment';
    return 'contact';
  });

  readonly fieldKey = computed<string>(() => (this.node().config?.['field_key'] as string) ?? '');

  readonly valueSource = computed<string>(
    () => (this.node().config?.['value_source'] as string) ?? 'literal',
  );

  readonly value = computed<string>(() => String(this.node().config?.['value'] ?? ''));

  constructor() {
    effect(() => {
      this.validityChange.emit(this.fieldKey().trim().length > 0 && this.value().length > 0);
    });
  }

  onFieldKeyChange(v: string): void {
    this.configChange.emit({ field_key: v });
  }
  onValueSourceChange(v: string): void {
    this.configChange.emit({ value_source: v });
  }
  onValueChange(v: string): void {
    this.configChange.emit({ value: v });
  }
}

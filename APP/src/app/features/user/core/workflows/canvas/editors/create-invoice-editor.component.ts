import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CanvasNode } from '../canvas-state.service';

@Component({
  selector: 'app-create-invoice-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './create-invoice-editor.component.html',
})
export class CreateInvoiceEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly templateId = computed<string>(
    () => (this.node().config?.['template_id'] as string) ?? '',
  );
  readonly amount = computed<string>(() => String(this.node().config?.['amount'] ?? ''));
  readonly dueInDays = computed<number>(() => (this.node().config?.['due_in_days'] as number) ?? 7);

  constructor() {
    effect(() =>
      this.validityChange.emit(this.templateId().length > 0 && this.amount().trim().length > 0),
    );
  }

  onTemplateChange(v: string): void {
    this.configChange.emit({ template_id: v });
  }
  onAmountChange(v: string): void {
    this.configChange.emit({ amount: v });
  }
  onDueChange(v: number): void {
    this.configChange.emit({ due_in_days: Number.isFinite(v) ? v : 7 });
  }
}

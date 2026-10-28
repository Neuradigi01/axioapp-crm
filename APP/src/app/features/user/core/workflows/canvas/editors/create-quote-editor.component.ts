import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CanvasNode } from '../canvas-state.service';

@Component({
  selector: 'app-create-quote-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './create-quote-editor.component.html',
})
export class CreateQuoteEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly templateId = computed<string>(
    () => (this.node().config?.['template_id'] as string) ?? '',
  );
  readonly amount = computed<string>(() => String(this.node().config?.['amount'] ?? ''));
  readonly expiresInDays = computed<number>(
    () => (this.node().config?.['expires_in_days'] as number) ?? 14,
  );
  readonly sendEmail = computed<boolean>(
    () => (this.node().config?.['send_email'] as boolean) ?? true,
  );

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
  onExpiresChange(v: number): void {
    this.configChange.emit({ expires_in_days: Number.isFinite(v) ? v : 14 });
  }
  onSendEmailChange(v: boolean): void {
    this.configChange.emit({ send_email: v });
  }
}

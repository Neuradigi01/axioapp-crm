import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../../shared/forms/mobile-select.component';
import { CanvasNode } from '../canvas-state.service';

const CONVERSION_REASON_OPTIONS: ReadonlyArray<MobileSelectOption> = [
  { value: 'won', label: 'Won (deal closed)' },
  { value: 'qualified', label: 'Qualified' },
  { value: 'other', label: 'Other' },
];

/**
 * Covers 4 lifecycle node types: `lifecycle.mark_converted`,
 * `lifecycle.mark_unsubscribed`, `lifecycle.block`,
 * `lifecycle.archive`. Each takes an optional reason note;
 * `mark_converted` additionally takes a `conversion_reason` enum.
 */

@Component({
  selector: 'app-lifecycle-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, MobileSelectComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './lifecycle-editor.component.html',
})
export class LifecycleEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly conversionReasonOptions = CONVERSION_REASON_OPTIONS;

  readonly type = computed(() => this.node().type);

  readonly reason = computed<string>(() => (this.node().config?.['reason'] as string) ?? '');
  readonly conversionReason = computed<string>(
    () => (this.node().config?.['conversion_reason'] as string) ?? 'won',
  );

  constructor() {
    // All lifecycle ops are valid even without a reason (reason is
    // optional metadata for audit). Mark always valid here.
    effect(() => this.validityChange.emit(true));
  }

  isConvert(): boolean {
    return this.type() === 'lifecycle.mark_converted';
  }

  onReasonChange(v: string): void {
    this.configChange.emit({ reason: v });
  }
  onConversionReasonChange(v: string): void {
    this.configChange.emit({ conversion_reason: v });
  }
}

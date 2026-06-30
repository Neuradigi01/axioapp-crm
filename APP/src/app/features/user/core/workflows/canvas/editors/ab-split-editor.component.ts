import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  input,
  output,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CanvasNode } from '../canvas-state.service';


@Component({
  selector: 'app-ab-split-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './ab-split-editor.component.html',
})
export class AbSplitEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly weightA = computed<number>(() => {
    const weights = this.node().config?.['weights'] as number[] | undefined;
    if (Array.isArray(weights) && weights.length === 2) {
      const total = weights[0] + weights[1];
      return total > 0 ? Math.round((weights[0] / total) * 100) : 50;
    }
    return 50;
  });

  constructor() {
    effect(() => this.validityChange.emit(true));
  }

  onWeightAChange(v: number): void {
    const clamped = Math.max(0, Math.min(100, Number.isFinite(v) ? v : 50));
    this.configChange.emit({ weights: [clamped, 100 - clamped] });
  }

  weightBLabel(): number {
    return 100 - this.weightA();
  }
}

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


const UNITS = [
  { value: 'minutes', label: 'minute(s)', multiplier: 60 },
  { value: 'hours', label: 'hour(s)', multiplier: 3600 },
  { value: 'days', label: 'day(s)', multiplier: 86400 },
] as const;


@Component({
  selector: 'app-wait-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './wait-editor.component.html',
})
export class WaitEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly units = UNITS;

  readonly amount = computed<number>(
    () => (this.node().config?.['amount'] as number) ?? 1,
  );
  readonly unit = computed<string>(
    () => (this.node().config?.['unit'] as string) ?? 'hours',
  );
  readonly delaySeconds = computed<number>(() => {
    const u = UNITS.find((x) => x.value === this.unit());
    return Math.max(1, this.amount()) * (u?.multiplier ?? 3600);
  });

  constructor() {
    effect(() => this.validityChange.emit(this.amount() > 0));
  }

  onAmountChange(v: number): void {
    const sane = Number.isFinite(v) && v > 0 ? v : 1;
    const u = UNITS.find((x) => x.value === this.unit());
    this.configChange.emit({
      amount: sane,
      delay_seconds: sane * (u?.multiplier ?? 3600),
    });
  }

  onUnitChange(v: string): void {
    const u = UNITS.find((x) => x.value === v);
    this.configChange.emit({
      unit: v,
      delay_seconds: this.amount() * (u?.multiplier ?? 3600),
    });
  }
}

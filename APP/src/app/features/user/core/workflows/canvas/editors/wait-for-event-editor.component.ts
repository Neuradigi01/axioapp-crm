import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CanvasNode } from '../canvas-state.service';
import { WAITABLE_EVENT_TYPES } from './editor-contract';

const UNITS = [
  { value: 'minutes', label: 'minute(s)', multiplier: 60 },
  { value: 'hours', label: 'hour(s)', multiplier: 3600 },
  { value: 'days', label: 'day(s)', multiplier: 86400 },
] as const;

@Component({
  selector: 'app-wait-for-event-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './wait-for-event-editor.component.html',
})
export class WaitForEventEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly waitableEvents = WAITABLE_EVENT_TYPES;
  readonly units = UNITS;

  readonly eventType = computed<string>(() => (this.node().config?.['event_type'] as string) ?? '');
  readonly amount = computed<number>(
    () => (this.node().config?.['max_wait_amount'] as number) ?? 24,
  );
  readonly unit = computed<string>(
    () => (this.node().config?.['max_wait_unit'] as string) ?? 'hours',
  );
  readonly contactMatch = computed<boolean>(
    () => (this.node().config?.['contact_match'] as boolean) ?? true,
  );

  constructor() {
    effect(() => this.validityChange.emit(this.eventType().length > 0 && this.amount() > 0));
  }

  onEventChange(v: string): void {
    this.configChange.emit({ event_type: v });
  }
  onContactMatchChange(v: boolean): void {
    this.configChange.emit({ contact_match: v });
  }

  onAmountChange(v: number): void {
    const sane = Number.isFinite(v) && v > 0 ? v : 1;
    const u = UNITS.find((x) => x.value === this.unit());
    this.configChange.emit({
      max_wait_amount: sane,
      max_wait_seconds: sane * (u?.multiplier ?? 3600),
    });
  }

  onUnitChange(v: string): void {
    const u = UNITS.find((x) => x.value === v);
    this.configChange.emit({
      max_wait_unit: v,
      max_wait_seconds: this.amount() * (u?.multiplier ?? 3600),
    });
  }
}

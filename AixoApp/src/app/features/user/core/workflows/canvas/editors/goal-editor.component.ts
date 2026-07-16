import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CanvasNode } from '../canvas-state.service';

@Component({
  selector: 'app-goal-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './goal-editor.component.html',
})
export class GoalEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly name = computed<string>(() => (this.node().config?.['name'] as string) ?? '');
  readonly outcomeLabel = computed<string>(
    () => (this.node().config?.['outcome_label'] as string) ?? 'goal_reached',
  );

  constructor() {
    effect(() => this.validityChange.emit(this.name().trim().length > 0));
  }

  onNameChange(v: string): void {
    this.configChange.emit({ name: v });
  }
  onOutcomeChange(v: string): void {
    this.configChange.emit({ outcome_label: v });
  }
}

import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CanvasNode } from '../canvas-state.service';

@Component({
  selector: 'app-create-task-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './create-task-editor.component.html',
})
export class CreateTaskEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly title = computed<string>(() => (this.node().config?.['title'] as string) ?? '');
  readonly description = computed<string>(
    () => (this.node().config?.['description'] as string) ?? '',
  );
  readonly assignee = computed<string>(
    () => (this.node().config?.['assignee'] as string) ?? 'lead.owner',
  );
  readonly dueInDays = computed<number>(() => (this.node().config?.['due_in_days'] as number) ?? 1);

  constructor() {
    effect(() => this.validityChange.emit(this.title().trim().length > 0));
  }

  onTitleChange(v: string): void {
    this.configChange.emit({ title: v });
  }
  onDescriptionChange(v: string): void {
    this.configChange.emit({ description: v });
  }
  onAssigneeChange(v: string): void {
    this.configChange.emit({ assignee: v });
  }
  onDueChange(v: number): void {
    this.configChange.emit({ due_in_days: Number.isFinite(v) ? v : 1 });
  }
}

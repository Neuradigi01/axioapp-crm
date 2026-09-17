import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../../shared/forms/mobile-select.component';
import { CanvasNode } from '../canvas-state.service';

const ASSIGNEE_OPTIONS: ReadonlyArray<MobileSelectOption> = [
  { value: 'lead.owner', label: 'Lead owner' },
  { value: 'contact.assigned_to', label: "Contact's assigned rep" },
  { value: 'workflow.owner', label: 'Workflow owner' },
];

@Component({
  selector: 'app-create-task-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, MobileSelectComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './create-task-editor.component.html',
})
export class CreateTaskEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly assigneeOptions = ASSIGNEE_OPTIONS;

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

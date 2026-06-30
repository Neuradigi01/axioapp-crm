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
  selector: 'app-create-appointment-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './create-appointment-editor.component.html',
})
export class CreateAppointmentEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly title = computed<string>(
    () => (this.node().config?.['title'] as string) ?? '',
  );
  readonly assignee = computed<string>(
    () => (this.node().config?.['assignee'] as string) ?? 'lead.owner',
  );
  readonly scheduleInHours = computed<number>(
    () => (this.node().config?.['schedule_in_hours'] as number) ?? 24,
  );
  readonly durationMinutes = computed<number>(
    () => (this.node().config?.['duration_minutes'] as number) ?? 30,
  );

  constructor() {
    effect(() => this.validityChange.emit(this.title().trim().length > 0));
  }

  onTitleChange(v: string): void { this.configChange.emit({ title: v }); }
  onAssigneeChange(v: string): void { this.configChange.emit({ assignee: v }); }
  onScheduleChange(v: number): void {
    this.configChange.emit({ schedule_in_hours: Number.isFinite(v) ? v : 24 });
  }
  onDurationChange(v: number): void {
    this.configChange.emit({ duration_minutes: Number.isFinite(v) ? v : 30 });
  }
}

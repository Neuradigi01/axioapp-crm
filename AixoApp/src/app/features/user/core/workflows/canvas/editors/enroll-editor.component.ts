import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CanvasNode } from '../canvas-state.service';

/**
 * Handles 4 lifecycle nodes that link the contact to another
 * workflow / sequence: `lifecycle.enroll_workflow`,
 * `lifecycle.enroll_sequence`, `lifecycle.remove_workflow`,
 * `lifecycle.remove_sequence`. All four take a single target id.
 */

@Component({
  selector: 'app-enroll-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './enroll-editor.component.html',
})
export class EnrollEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly type = computed(() => this.node().type);

  readonly targetId = computed<string>(() => (this.node().config?.['target_id'] as string) ?? '');

  constructor() {
    effect(() => this.validityChange.emit(this.targetId().trim().length > 0));
  }

  isWorkflow(): boolean {
    return this.type().endsWith('_workflow');
  }

  isEnroll(): boolean {
    return this.type().startsWith('lifecycle.enroll_');
  }

  onTargetChange(v: string): void {
    this.configChange.emit({ target_id: v });
  }
}

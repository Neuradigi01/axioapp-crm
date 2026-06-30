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


/**
 * Handles every `routing.*` node — the dispatcher passes the node and
 * the editor infers the mode from `node.type` (round_robin /
 * least_loaded / territory / skill / specific_user). Operator picks
 * the pool spec + target attachment + fallback resolver.
 */


@Component({
  selector: 'app-routing-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './routing-editor.component.html',
})
export class RoutingEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly mode = computed<string>(() => this.node().type.replace('routing.', ''));

  readonly poolType = computed<string>(
    () => (this.node().config?.['pool_type'] as string) ?? 'role',
  );
  readonly poolValue = computed<string>(
    () => (this.node().config?.['pool_value'] as string) ?? '',
  );
  readonly target = computed<string>(
    () => (this.node().config?.['target'] as string) ?? 'lead.assigned_to',
  );
  readonly fallback = computed<string>(
    () => (this.node().config?.['fallback'] as string) ?? 'workflow.owner',
  );
  readonly specificUserId = computed<string>(
    () => (this.node().config?.['specific_user_id'] as string) ?? '',
  );

  constructor() {
    effect(() => {
      const m = this.mode();
      if (m === 'specific_user') {
        this.validityChange.emit(this.specificUserId().trim().length > 0);
      } else {
        this.validityChange.emit(this.poolValue().trim().length > 0);
      }
    });
  }

  isSpecificUser(): boolean { return this.mode() === 'specific_user'; }

  onPoolTypeChange(v: string): void { this.configChange.emit({ pool_type: v }); }
  onPoolValueChange(v: string): void { this.configChange.emit({ pool_value: v }); }
  onTargetChange(v: string): void { this.configChange.emit({ target: v }); }
  onFallbackChange(v: string): void { this.configChange.emit({ fallback: v }); }
  onSpecificUserChange(v: string): void { this.configChange.emit({ specific_user_id: v }); }
}

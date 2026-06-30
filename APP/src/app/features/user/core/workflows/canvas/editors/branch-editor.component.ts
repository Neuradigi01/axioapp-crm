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
import { ConditionsBuilderComponent } from '../conditions-builder.component';
import {
  ALWAYS_AVAILABLE,
  ConditionNode,
} from './editor-contract';


export interface Branch {
  label: string;
  conditions: ConditionNode | null;
}


/**
 * `branch.if` config editor — yes / no fork. Operator configures the
 * `yes` branch's conditions; the `no` branch is implicit (fallthrough
 * when no other branch matches). Backend already enforces the dual
 * output edges via the node-type registry.
 */


@Component({
  selector: 'app-branch-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, ConditionsBuilderComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './branch-editor.component.html',
})
export class BranchEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly conditions = computed<ConditionNode | null>(
    () => (this.node().config?.['conditions'] as ConditionNode | null) ?? null,
  );

  readonly variableGroups = [ALWAYS_AVAILABLE];

  constructor() {
    effect(() => this.validityChange.emit(this.conditions() !== null));
  }

  onConditionsChange(tree: ConditionNode | null): void {
    this.configChange.emit({ conditions: tree });
  }
}

import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { CanvasNode } from '../canvas-state.service';

@Component({
  selector: 'app-switch-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './switch-editor.component.html',
})
export class SwitchEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly path = computed<string>(() => (this.node().config?.['path'] as string) ?? '');
  readonly cases = computed<string[]>(() => (this.node().config?.['cases'] as string[]) ?? []);

  constructor() {
    effect(() =>
      this.validityChange.emit(this.path().trim().length > 0 && this.cases().length > 0),
    );
  }

  onPathChange(v: string): void {
    this.configChange.emit({ path: v });
  }

  onCaseChange(idx: number, v: string): void {
    const next = [...this.cases()];
    next[idx] = v;
    this.configChange.emit({ cases: next });
  }

  addCase(): void {
    this.configChange.emit({ cases: [...this.cases(), ''] });
  }

  removeCase(idx: number): void {
    const next = this.cases().filter((_, i) => i !== idx);
    this.configChange.emit({ cases: next });
  }
}

import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../../shared/forms/mobile-select.component';
import { CanvasNode } from '../canvas-state.service';

const SCORE_MODE_OPTIONS: ReadonlyArray<MobileSelectOption> = [
  { value: 'set', label: 'Set to literal' },
  { value: 'add', label: 'Add delta' },
  { value: 'subtract', label: 'Subtract delta' },
];

/**
 * Handles 5 nodes that share the same "pick a label, optionally a delta"
 * shape: `tag.add`, `tag.remove`, `list.add`, `list.remove`,
 * `lifecycle.set_score`. The dispatcher passes the node, the editor
 * picks the right inputs from `node.type`.
 */

@Component({
  selector: 'app-tagging-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, MobileSelectComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './tagging-editor.component.html',
})
export class TaggingEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly scoreModeOptions = SCORE_MODE_OPTIONS;

  readonly type = computed(() => this.node().type);

  readonly tagName = computed<string>(() => (this.node().config?.['tag'] as string) ?? '');
  readonly listId = computed<string>(() => (this.node().config?.['list_id'] as string) ?? '');
  readonly scoreMode = computed<string>(() => (this.node().config?.['mode'] as string) ?? 'set');
  readonly scoreValue = computed<number>(() => (this.node().config?.['value'] as number) ?? 0);

  constructor() {
    effect(() => {
      const t = this.type();
      if (t === 'tag.add' || t === 'tag.remove') {
        this.validityChange.emit(this.tagName().trim().length > 0);
      } else if (t === 'list.add' || t === 'list.remove') {
        this.validityChange.emit(this.listId().trim().length > 0);
      } else if (t === 'lifecycle.set_score') {
        this.validityChange.emit(Number.isFinite(this.scoreValue()));
      } else {
        this.validityChange.emit(true);
      }
    });
  }

  isTag(): boolean {
    return this.type().startsWith('tag.');
  }
  isList(): boolean {
    return this.type().startsWith('list.');
  }
  isScore(): boolean {
    return this.type() === 'lifecycle.set_score';
  }

  onTagChange(v: string): void {
    this.configChange.emit({ tag: v });
  }
  onListIdChange(v: string): void {
    this.configChange.emit({ list_id: v });
  }
  onScoreModeChange(v: string): void {
    this.configChange.emit({ mode: v });
  }
  onScoreValueChange(v: number): void {
    this.configChange.emit({ value: Number.isFinite(v) ? v : 0 });
  }
}

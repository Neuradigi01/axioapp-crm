import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CanvasNode } from '../canvas-state.service';

@Component({
  selector: 'app-create-note-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './create-note-editor.component.html',
})
export class CreateNoteEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly body = computed<string>(() => (this.node().config?.['body'] as string) ?? '');
  readonly entity = computed<string>(() => (this.node().config?.['entity'] as string) ?? 'contact');

  constructor() {
    effect(() => this.validityChange.emit(this.body().trim().length > 0));
  }

  onBodyChange(v: string): void {
    this.configChange.emit({ body: v });
  }
  onEntityChange(v: string): void {
    this.configChange.emit({ entity: v });
  }
}

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
import { SEND_CATEGORIES } from './editor-contract';
import { readSendState, sendIsValid } from './send-editor-shared';


@Component({
  selector: 'app-send-ig-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './send-ig-editor.component.html',
})
export class SendIgEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();
  readonly categoryOptions = SEND_CATEGORIES;
  readonly state = computed(() => readSendState(this.node()));
  constructor() {
    effect(() => this.validityChange.emit(sendIsValid(this.state())));
  }
  onTemplateChange(v: string): void { this.configChange.emit({ template_id: v }); }
  onRecipientChange(v: string): void { this.configChange.emit({ recipient: v }); }
  onCustomChange(v: string): void { this.configChange.emit({ recipient_custom: v }); }
  onCategoryChange(v: string): void { this.configChange.emit({ category: v }); }
}

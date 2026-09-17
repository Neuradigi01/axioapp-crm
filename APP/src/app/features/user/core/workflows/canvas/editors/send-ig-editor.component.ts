import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../../shared/forms/mobile-select.component';
import { CanvasNode } from '../canvas-state.service';
import { SEND_CATEGORIES } from './editor-contract';
import { readSendState, sendIsValid } from './send-editor-shared';

const IG_RECIPIENT_OPTIONS: ReadonlyArray<MobileSelectOption> = [
  { value: 'contact.ig_id', label: "Contact's Instagram-scoped ID" },
  { value: 'custom', label: 'Custom path…' },
];

@Component({
  selector: 'app-send-ig-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, MobileSelectComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './send-ig-editor.component.html',
})
export class SendIgEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();
  readonly categoryOptions = SEND_CATEGORIES;
  readonly recipientOptions = IG_RECIPIENT_OPTIONS;
  readonly categorySelectOptions = computed<MobileSelectOption[]>(() =>
    this.categoryOptions.map((c) => ({ value: c.value, label: c.label })),
  );
  readonly state = computed(() => readSendState(this.node()));
  constructor() {
    effect(() => this.validityChange.emit(sendIsValid(this.state())));
  }
  onTemplateChange(v: string): void {
    this.configChange.emit({ template_id: v });
  }
  onRecipientChange(v: string): void {
    this.configChange.emit({ recipient: v });
  }
  onCustomChange(v: string): void {
    this.configChange.emit({ recipient_custom: v });
  }
  onCategoryChange(v: string): void {
    this.configChange.emit({ category: v });
  }
}

import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CanvasNode } from '../canvas-state.service';
import { EMAIL_RECIPIENTS, SEND_CATEGORIES } from './editor-contract';
import { readSendState, sendIsValid } from './send-editor-shared';

@Component({
  selector: 'app-send-email-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './send-email-editor.component.html',
})
export class SendEmailEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly recipientOptions = EMAIL_RECIPIENTS;
  readonly categoryOptions = SEND_CATEGORIES;

  readonly state = computed(() => readSendState(this.node()));

  readonly trackOpens = computed<boolean>(
    () => (this.node().config?.['track_opens'] as boolean) ?? true,
  );
  readonly trackClicks = computed<boolean>(
    () => (this.node().config?.['track_clicks'] as boolean) ?? true,
  );

  constructor() {
    effect(() => this.validityChange.emit(sendIsValid(this.state())));
  }

  onTemplateChange(value: string): void {
    this.configChange.emit({ template_id: value });
  }
  onRecipientChange(value: string): void {
    this.configChange.emit({ recipient: value });
  }
  onCustomChange(value: string): void {
    this.configChange.emit({ recipient_custom: value });
  }
  onCategoryChange(value: string): void {
    this.configChange.emit({ category: value });
  }
  onTrackOpensChange(value: boolean): void {
    this.configChange.emit({ track_opens: value });
  }
  onTrackClicksChange(value: boolean): void {
    this.configChange.emit({ track_clicks: value });
  }
}

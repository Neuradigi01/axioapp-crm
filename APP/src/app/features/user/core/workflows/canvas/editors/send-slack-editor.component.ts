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
 * Slack send — diverges from the other channels because the
 * destination is a Slack channel name (or operator-provided webhook),
 * not a contact recipient. `template_id` still points at a central
 * message template — Slack's bot reads the rendered text + posts it.
 */


@Component({
  selector: 'app-send-slack-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './send-slack-editor.component.html',
})
export class SendSlackEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly templateId = computed<string>(
    () => (this.node().config?.['template_id'] as string) ?? '',
  );
  readonly slackChannel = computed<string>(
    () => (this.node().config?.['slack_channel'] as string) ?? '',
  );

  constructor() {
    effect(() =>
      this.validityChange.emit(
        this.templateId().length > 0 && this.slackChannel().trim().length > 0,
      ),
    );
  }

  onTemplateChange(v: string): void { this.configChange.emit({ template_id: v }); }
  onChannelChange(v: string): void { this.configChange.emit({ slack_channel: v }); }
}

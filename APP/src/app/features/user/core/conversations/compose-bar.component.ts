import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import {
  EmailTemplateRenderResponse,
} from '../services/email-templates-api.service';
import { EmailTemplatePickerComponent } from '../shared/email/template-picker.component';

/**
 * Compose bar — input + send + "Let AI handle it" toggle. Enter
 * submits, Shift+Enter inserts a newline. The AI toggle writes the
 * `ai_handling` flag via the parent's `toggleAi` output.
 *
 * Step 10 wires the email-template picker into the right-hand
 * action stack when the active conversation has `channel='email'`.
 * Picker selection fills the textarea with the rendered `body_text`
 * — the existing send pipeline carries that as the message text.
 * (HTML body lands when we ship the dedicated email compose surface
 * — out of scope for v1.)
 */
@Component({
  selector: 'app-compose-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    LucideAngularModule,
    EmailTemplatePickerComponent,
  ],
  templateUrl: './compose-bar.component.html',
})
export class ComposeBarComponent {
  @Input() aiHandling = false;
  /** Active conversation channel — controls whether the email
   *  template picker renders. WhatsApp / SMS / future channels don't
   *  show it. */
  @Input() channel: string | null = null;
  /** Contact id for the conversation — passes through to the picker
   *  so the server-side render has somebody to substitute variables
   *  against. */
  @Input() contactId: string | null = null;
  /** Optional lead id when the conversation is lead-linked. */
  @Input() leadId: string | null = null;

  @Output() readonly send = new EventEmitter<string>();
  @Output() readonly toggleAi = new EventEmitter<boolean>();

  protected readonly text = signal<string>('');
  protected readonly templateError = signal<string | null>(null);

  protected onTextChange(value: string): void {
    this.text.set(value);
  }

  protected submit(): void {
    const v = this.text().trim();
    if (!v) return;
    this.send.emit(v);
    this.text.set('');
  }

  protected onKey(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.submit();
    }
  }

  protected flipAi(): void {
    this.toggleAi.emit(!this.aiHandling);
  }

  protected onTemplateSelected(resp: EmailTemplateRenderResponse): void {
    this.templateError.set(null);
    // Fill the textarea with the plain-text fallback — the existing
    // send pipeline carries `text`, not `body_html`. The dedicated
    // email-compose surface (out of scope for v1) will plug body_html
    // and subject when it ships.
    this.text.set(resp.body_text || resp.body_html);
  }

  protected onTemplateError(message: string): void {
    this.templateError.set(message);
  }

  protected dismissTemplateError(): void {
    this.templateError.set(null);
  }
}

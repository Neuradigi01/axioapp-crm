import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';

import { MobileSelectComponent } from '../../../shared/forms/mobile-select.component';
import { TemplateRead, TemplatesApiService } from '../../../templates/templates-api.service';
import { CanvasNode } from '../canvas-state.service';
import { buildTemplateOptions } from './send-editor-shared';

/**
 * Slack send — diverges from the other channels because the
 * destination is a Slack channel name (or operator-provided webhook),
 * not a contact recipient. `template_id` still points at a central
 * message template — Slack's bot reads the rendered text + posts it.
 *
 * Template surface parity with the email/whatsapp/sms editors
 * (workflow-scheduling follow-up 2026-08-06): load the org's published
 * Slack templates and render a picker instead of asking the operator
 * to paste a raw UUID.
 */

@Component({
  selector: 'app-send-slack-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, MobileSelectComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './send-slack-editor.component.html',
})
export class SendSlackEditorComponent {
  private readonly api = inject(TemplatesApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly templateId = computed<string>(
    () => (this.node().config?.['template_id'] as string) ?? '',
  );
  readonly slackChannel = computed<string>(
    () => (this.node().config?.['slack_channel'] as string) ?? '',
  );

  /** Published Slack templates for the org — the picker options. */
  readonly templates = signal<TemplateRead[] | null>(null);
  readonly loadError = signal<string | null>(null);

  /** Mapped for `crm-mobile-select` — placeholder + loaded templates +
   *  fallback for the stored id when it's not in the fetch (deleted,
   *  archived, or outside the paginated slice). */
  readonly templateOptions = computed(() =>
    buildTemplateOptions(this.templates(), this.templateId()),
  );

  constructor() {
    effect(() =>
      this.validityChange.emit(
        this.templateId().length > 0 && this.slackChannel().trim().length > 0,
      ),
    );
    this._loadTemplates();
  }

  private _loadTemplates(): void {
    // Slack has no first-class 'slack' template channel — the bot
    // renders any template's body text into the target Slack channel.
    // List every published template so the operator can pick freely.
    this.api
      .list({ internal_status: 'published', limit: 200 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => this.templates.set(res.items),
        error: () => {
          this.templates.set([]);
          this.loadError.set('Could not load templates. Retry the panel.');
        },
      });
  }

  onTemplateChange(v: string): void {
    this.configChange.emit({ template_id: v });
  }
  onChannelChange(v: string): void {
    this.configChange.emit({ slack_channel: v });
  }
}

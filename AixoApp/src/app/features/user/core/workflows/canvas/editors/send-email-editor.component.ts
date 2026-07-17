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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { TemplateRead, TemplatesApiService } from '../../../templates/templates-api.service';
import { CanvasNode } from '../canvas-state.service';
import { EMAIL_RECIPIENTS, SEND_CATEGORIES } from './editor-contract';
import { readSendState, sendIsValid } from './send-editor-shared';

@Component({
  selector: 'app-send-email-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './send-email-editor.component.html',
})
export class SendEmailEditorComponent {
  private readonly api = inject(TemplatesApiService);
  private readonly destroyRef = inject(DestroyRef);

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

  /** All published Email templates for the org — the picker options. */
  readonly templates = signal<TemplateRead[] | null>(null);
  readonly loadError = signal<string | null>(null);

  constructor() {
    effect(() => this.validityChange.emit(sendIsValid(this.state())));
    this._loadTemplates();
  }

  private _loadTemplates(): void {
    this.api
      .list({ channel: 'email', internal_status: 'published', limit: 200 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => this.templates.set(res.items),
        error: () => {
          this.templates.set([]);
          this.loadError.set('Could not load templates. Retry the panel.');
        },
      });
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

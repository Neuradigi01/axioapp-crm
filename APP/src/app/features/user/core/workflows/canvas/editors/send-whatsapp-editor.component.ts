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
import { PHONE_RECIPIENTS, SEND_CATEGORIES } from './editor-contract';
import { readSendState, sendIsValid } from './send-editor-shared';

@Component({
  selector: 'app-send-whatsapp-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './send-whatsapp-editor.component.html',
})
export class SendWhatsAppEditorComponent {
  private readonly api = inject(TemplatesApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly recipientOptions = PHONE_RECIPIENTS;
  readonly categoryOptions = SEND_CATEGORIES;

  readonly state = computed(() => readSendState(this.node()));

  /** Only Meta-approved WA templates ship. Filter by external_status
   *  so the dropdown never lists a pending / rejected row — sending
   *  one would fail at dispatch time anyway. */
  readonly templates = signal<TemplateRead[] | null>(null);
  readonly loadError = signal<string | null>(null);

  constructor() {
    effect(() => this.validityChange.emit(sendIsValid(this.state())));
    this._loadTemplates();
  }

  private _loadTemplates(): void {
    this.api
      .list({
        channel: 'whatsapp',
        internal_status: 'published',
        external_status: 'approved',
        limit: 200,
      })
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

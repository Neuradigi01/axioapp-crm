/**
 * URL knowledge panel (``tasks/ai-assistants`` Step 11).
 *
 * Simple URL + title + Add. The backend rejects private/link-local
 * hosts at ``_pre_check_url`` before the row is even inserted — we
 * surface that 422 verbatim so the operator sees exactly which
 * SSRF check fired (``private_ip_rejected`` / ``bad_scheme`` / etc.).
 */
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '../../../../../../../shared/components/toast/toast.service';
import { AiAssistantsApiService } from '../../../ai-assistants-api.service';

@Component({
  selector: 'app-knowledge-url-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './url-panel.component.html',
})
export class UrlPanelComponent {
  private readonly api = inject(AiAssistantsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);

  @Input({ required: true }) assistantId!: string;
  @Output() readonly created = new EventEmitter<void>();

  protected readonly url = signal('');
  protected readonly title = signal('');
  protected readonly saving = signal(false);

  protected readonly canSave = computed(
    () => !this.saving() && /^https?:\/\/\S+/i.test(this.url().trim()),
  );

  protected onUrlInput(event: Event): void {
    this.url.set((event.target as HTMLInputElement).value);
  }

  protected onTitleInput(event: Event): void {
    this.title.set((event.target as HTMLInputElement).value);
  }

  protected save(): void {
    if (!this.canSave()) return;
    const trimmedUrl = this.url().trim();
    this.saving.set(true);
    this.api
      .addKnowledgeUrl(this.assistantId, {
        url: trimmedUrl,
        title: this.title().trim() || trimmedUrl,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.saving.set(false);
          if (resp.duplicate) {
            this.toast.info('This URL is already in your knowledge base.');
          } else {
            this.url.set('');
            this.title.set('');
            this.toast.success('URL added', {
              subtitle: 'Processing now. It will be ready for the assistant shortly.',
            });
          }
          this.created.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.toast.error('Could not add URL', {
            subtitle: extractApiError(err) ?? 'Please try again.',
          });
        },
      });
  }
}

/**
 * Custom-text knowledge panel (``tasks/ai-assistants`` Step 11).
 *
 * Simple title + textarea → POST /knowledge/text. The body cap comes
 * from the backend (20 MB post-extract); the frontend enforces a
 * 100 000-char soft cap on the textarea so the counter widget stays
 * useful. Anything past that fails at the schema layer as a 422.
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
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '../../../../../../../shared/components/toast/toast.service';
import { AiAssistantsApiService } from '../../../ai-assistants-api.service';

const CHAR_LIMIT = 100_000;

@Component({
  selector: 'app-knowledge-custom-data-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  templateUrl: './custom-data-panel.component.html',
})
export class CustomDataPanelComponent {
  private readonly api = inject(AiAssistantsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);

  @Input({ required: true }) assistantId!: string;
  @Output() readonly created = new EventEmitter<void>();

  protected readonly title = signal('');
  protected readonly body = signal('');
  protected readonly saving = signal(false);

  protected readonly charLimit = CHAR_LIMIT;
  protected readonly charCount = computed(() => this.body().length);
  protected readonly canSave = computed(
    () => !this.saving() && this.body().trim().length > 0 && this.charCount() <= CHAR_LIMIT,
  );

  protected onTitleInput(event: Event): void {
    this.title.set((event.target as HTMLInputElement).value);
  }

  protected onBodyInput(event: Event): void {
    this.body.set((event.target as HTMLTextAreaElement).value);
  }

  protected save(): void {
    if (!this.canSave()) return;
    this.saving.set(true);
    this.api
      .addKnowledgeText(this.assistantId, {
        title: this.title().trim() || 'Untitled',
        body_text: this.body(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.saving.set(false);
          if (resp.duplicate) {
            this.toast.info('This text is already in your knowledge base.');
          } else {
            this.title.set('');
            this.body.set('');
            this.toast.success('Custom data added', {
              subtitle: 'Processing now. It will be ready for the assistant shortly.',
            });
          }
          this.created.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.toast.error('Could not save custom data', {
            subtitle: extractApiError(err) ?? 'Please try again.',
          });
        },
      });
  }
}

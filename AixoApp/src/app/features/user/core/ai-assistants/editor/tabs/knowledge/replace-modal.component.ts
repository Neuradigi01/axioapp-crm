/**
 * Replace-knowledge modal (``tasks/ai-assistants`` Step 11).
 *
 * Wraps the upload-file flow with a warning banner + the "this
 * replaces the existing source" copy. Backend's replace endpoint
 * ingests the new upload as a fresh row + retires the old row —
 * mid-swap the old chunks stay reachable so a preview call never
 * sees a "no context" gap.
 */
import { CommonModule } from '@angular/common';
import { HttpErrorResponse, HttpEvent, HttpEventType, HttpResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  AiAssistantKnowledgeRow,
  AiAssistantsApiService,
  KnowledgeCreateResponse,
} from '../../../ai-assistants-api.service';

const MAX_BYTES = 90 * 1024 * 1024;

@Component({
  selector: 'app-knowledge-replace-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './replace-modal.component.html',
})
export class ReplaceModalComponent {
  private readonly api = inject(AiAssistantsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input({ required: true }) assistantId!: string;
  @Input({ required: true }) knowledge!: AiAssistantKnowledgeRow;
  @Output() readonly replaced = new EventEmitter<void>();
  @Output() readonly dismissed = new EventEmitter<void>();

  protected readonly uploading = signal(false);
  protected readonly progress = signal(0);
  protected readonly error = signal<string | null>(null);

  protected onFilePicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (file) this.startUpload(file);
  }

  protected close(): void {
    if (this.uploading()) return;
    this.dismissed.emit();
  }

  private startUpload(file: File): void {
    if (!file.size) {
      this.error.set('File is empty.');
      return;
    }
    if (file.size > MAX_BYTES) {
      this.error.set('File exceeds the 90 MB limit.');
      return;
    }
    this.error.set(null);
    this.uploading.set(true);
    this.progress.set(0);
    this.api
      .replaceKnowledgeFile(this.assistantId, this.knowledge.id, file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (event) => this.handleEvent(event),
        error: (err: HttpErrorResponse) => {
          this.uploading.set(false);
          this.progress.set(0);
          this.error.set(extractApiError(err) ?? 'Replace failed.');
        },
      });
  }

  private handleEvent(event: HttpEvent<KnowledgeCreateResponse>): void {
    if (event.type === HttpEventType.UploadProgress) {
      if (event.total) {
        this.progress.set(Math.round((event.loaded / event.total) * 100));
      }
      return;
    }
    if (event instanceof HttpResponse) {
      this.uploading.set(false);
      this.progress.set(100);
      this.replaced.emit();
    }
  }
}

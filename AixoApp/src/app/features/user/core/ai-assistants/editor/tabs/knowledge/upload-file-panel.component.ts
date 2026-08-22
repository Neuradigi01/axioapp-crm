/**
 * File-upload panel (``tasks/ai-assistants`` Step 11).
 *
 * Drop zone matching the Pabbly reference. Client-side pre-check
 * (size + extension) surfaces the friendly error immediately; the
 * server does the authoritative validation (magic-byte sniff,
 * Windows-reserved names, size cap) in ``file_upload.py``.
 *
 * Progress: uses ``HttpClient.request()`` with ``reportProgress:
 * true`` so the drop zone can show a 0–100% bar during the upload.
 * When the terminal ``HttpResponse`` arrives we emit ``created`` so
 * the parent tab bumps the list-refresh signal.
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
  AiAssistantsApiService,
  KnowledgeCreateResponse,
} from '../../../ai-assistants-api.service';

// Keep in lock-step with :mod:`~core.ai_assistants.file_upload._MAX_UPLOAD_BYTES`.
const MAX_BYTES = 90 * 1024 * 1024;
const ACCEPT_EXTENSIONS: readonly string[] = ['.pdf', '.txt'];
// Matches the accept="" on the file input — kept as a string for the
// template so the OS file-picker filters to the same list.
const ACCEPT_ATTR = ACCEPT_EXTENSIONS.join(',');

@Component({
  selector: 'app-knowledge-upload-file-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './upload-file-panel.component.html',
})
export class UploadFilePanelComponent {
  private readonly api = inject(AiAssistantsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input({ required: true }) assistantId!: string;
  @Output() readonly created = new EventEmitter<void>();

  protected readonly dragActive = signal(false);
  protected readonly uploading = signal(false);
  protected readonly progress = signal<number>(0);
  protected readonly error = signal<string | null>(null);
  /** Info banner text (dedup path). Cleared on next upload attempt. */
  protected readonly notice = signal<string | null>(null);

  protected readonly acceptAttr = ACCEPT_ATTR;

  protected onFilePicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    // Reset the input so the same file can be re-selected after an
    // error (browsers suppress the change event otherwise).
    input.value = '';
    if (file) this.startUpload(file);
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragActive.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) this.startUpload(file);
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragActive.set(true);
  }

  protected onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.dragActive.set(false);
  }

  private startUpload(file: File): void {
    this.error.set(null);
    this.notice.set(null);

    const preCheck = this.preCheck(file);
    if (preCheck) {
      this.error.set(preCheck);
      return;
    }

    this.uploading.set(true);
    this.progress.set(0);
    this.api
      .uploadKnowledgeFile(this.assistantId, file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (event) => this.handleEvent(event),
        error: (err: HttpErrorResponse) => {
          this.uploading.set(false);
          this.progress.set(0);
          this.error.set(extractApiError(err) ?? 'Upload failed.');
        },
      });
  }

  private preCheck(file: File): string | null {
    if (!file.size) return 'File is empty.';
    if (file.size > MAX_BYTES) return 'File exceeds the 90 MB limit.';
    const lower = file.name.toLowerCase();
    const okExt = ACCEPT_EXTENSIONS.some((ext) => lower.endsWith(ext));
    if (!okExt) return 'Only .pdf or .txt files are supported.';
    return null;
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
      const body = event.body;
      if (body?.duplicate) {
        this.notice.set('This file is already in your knowledge base.');
      }
      this.created.emit();
    }
  }
}

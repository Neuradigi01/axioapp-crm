import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  Output,
  ViewChild,
  computed,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import {
  EmailTemplateRenderResponse,
} from '../services/email-templates-api.service';
import { EmailTemplatePickerComponent } from '../shared/email/template-picker.component';


export type ComposerAttachmentType =
  | 'image'
  | 'video'
  | 'audio'
  | 'document';


export interface ComposerMediaPayload {
  file: File;
  type: ComposerAttachmentType;
  caption?: string;
}


// Mirror of backend per-type caps in `core/conversations/media_upload.py`.
// Frontend pre-validation gives instant feedback; the backend re-checks.
const MAX_SIZE_BYTES: Record<ComposerAttachmentType, number> = {
  image: 5 * 1024 * 1024,
  video: 16 * 1024 * 1024,
  audio: 16 * 1024 * 1024,
  document: 100 * 1024 * 1024,
};


// Tighter whitelist than the backend so the picker steers the user to
// a sensible choice. The backend trusts the user's `type` form field
// and does the authoritative MIME check itself.
const MIME_TO_TYPE: Array<[RegExp, ComposerAttachmentType]> = [
  [/^image\/(jpeg|png)$/, 'image'],
  [/^video\/(mp4|3gpp)$/, 'video'],
  [/^audio\/(aac|mp4|mpeg|amr|ogg)$/, 'audio'],
  [/^application\/pdf$/, 'document'],
  [/^application\/msword$/, 'document'],
  [/^application\/vnd\.openxmlformats-officedocument\..*$/, 'document'],
  [/^application\/vnd\.ms-(excel|powerpoint)$/, 'document'],
  [/^text\/(plain|csv)$/, 'document'],
];


function classifyFile(file: File): ComposerAttachmentType | null {
  for (const [pattern, type] of MIME_TO_TYPE) {
    if (pattern.test(file.type)) {
      return type;
    }
  }
  return null;
}


/**
 * Compose bar — input + send + "Let AI handle it" toggle + paperclip
 * attach + drag-and-drop (whatsapp-platform-upgrade Step 5).
 *
 * Enter submits, Shift+Enter inserts a newline. The textarea doubles
 * as the caption field when a media file is staged. A small preview
 * tile shows file metadata + a clear-on-X button so the user can
 * abort before sending. Media-attach is enabled only on WhatsApp
 * conversations — the paperclip button is hidden otherwise.
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
   *  template picker renders, and whether the paperclip is offered. */
  @Input() channel: string | null = null;
  /** Contact id for the conversation — passes through to the picker
   *  so the server-side render has somebody to substitute variables
   *  against. */
  @Input() contactId: string | null = null;
  /** Optional lead id when the conversation is lead-linked. */
  @Input() leadId: string | null = null;

  @Output() readonly send = new EventEmitter<string>();
  @Output() readonly sendMedia = new EventEmitter<ComposerMediaPayload>();
  @Output() readonly openInteractive = new EventEmitter<void>();
  @Output() readonly toggleAi = new EventEmitter<boolean>();

  @ViewChild('fileInput') private readonly fileInput!: ElementRef<HTMLInputElement>;

  protected readonly text = signal<string>('');
  protected readonly templateError = signal<string | null>(null);

  protected readonly stagedFile = signal<File | null>(null);
  protected readonly stagedType = signal<ComposerAttachmentType | null>(null);
  protected readonly mediaError = signal<string | null>(null);
  protected readonly isDragging = signal(false);

  protected readonly canAttachMedia = computed(
    () => this.channel === 'whatsapp',
  );
  protected readonly captionsSupported = computed(() => {
    const t = this.stagedType();
    return t === 'image' || t === 'video' || t === 'document';
  });
  protected readonly placeholder = computed(() => {
    if (!this.stagedFile()) {
      return 'Type a reply or let AI handle it…';
    }
    return this.captionsSupported()
      ? 'Add a caption (optional)…'
      : 'Audio messages don’t support captions';
  });

  protected onTextChange(value: string): void {
    this.text.set(value);
  }

  protected requestInteractive(): void {
    if (!this.canAttachMedia()) return;
    this.openInteractive.emit();
  }

  protected submit(): void {
    const file = this.stagedFile();
    const type = this.stagedType();
    const trimmed = this.text().trim();
    if (file && type) {
      const caption =
        this.captionsSupported() && trimmed ? trimmed : undefined;
      this.sendMedia.emit({ file, type, caption });
      this.clearStaged();
      this.text.set('');
      return;
    }
    if (!trimmed) return;
    this.send.emit(trimmed);
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
    this.text.set(resp.body_text || resp.body_html);
  }

  protected onTemplateError(message: string): void {
    this.templateError.set(message);
  }

  protected dismissTemplateError(): void {
    this.templateError.set(null);
  }

  // --- Media attach --------------------------------------------------

  protected openFilePicker(): void {
    if (!this.canAttachMedia()) return;
    this.fileInput?.nativeElement.click();
  }

  protected onFilePicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    if (file) {
      this.stageFile(file);
    }
    // Reset the input so the same file can be picked again after a
    // clear-and-retry flow.
    input.value = '';
  }

  protected clearStaged(): void {
    this.stagedFile.set(null);
    this.stagedType.set(null);
    this.mediaError.set(null);
  }

  protected dismissMediaError(): void {
    this.mediaError.set(null);
  }

  // Drag-and-drop hooks — bound to the wrapper div in the template.
  protected onDragOver(event: DragEvent): void {
    if (!this.canAttachMedia()) return;
    event.preventDefault();
    this.isDragging.set(true);
  }

  protected onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.isDragging.set(false);
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.isDragging.set(false);
    if (!this.canAttachMedia()) return;
    const file = event.dataTransfer?.files?.[0] ?? null;
    if (file) {
      this.stageFile(file);
    }
  }

  private stageFile(file: File): void {
    const type = classifyFile(file);
    if (!type) {
      this.mediaError.set(
        `Unsupported file type ${file.type || 'unknown'}. ` +
          'Allowed: JPEG/PNG images, MP4/3GPP video, AAC/MP3/OGG audio, ' +
          'PDF/DOCX/XLSX/PPTX/TXT/CSV documents.',
      );
      return;
    }
    const cap = MAX_SIZE_BYTES[type];
    if (file.size > cap) {
      this.mediaError.set(
        `File is ${Math.round(file.size / 1024 / 1024)}MB — the cap for ` +
          `${type} is ${Math.round(cap / 1024 / 1024)}MB.`,
      );
      return;
    }
    this.mediaError.set(null);
    this.stagedFile.set(file);
    this.stagedType.set(type);
  }

  protected formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }
}

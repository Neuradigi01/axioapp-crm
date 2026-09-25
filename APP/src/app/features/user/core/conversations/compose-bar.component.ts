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

import { EmailTemplateRenderResponse } from '../services/email-templates-api.service';
import { EmailTemplatePickerComponent } from '../shared/email/template-picker.component';
import { SendFromPickerComponent } from '../whatsapp/shared/send-from-picker.component';
import { ConversationMessage } from './conversations-api.service';
import { UserMini } from '../shared/services/users-directory.service';

export type ComposerAttachmentType = 'image' | 'video' | 'audio' | 'document';

export interface ComposerMediaPayload {
  file: File;
  type: ComposerAttachmentType;
  caption?: string;
}

/**
 * Internal note payload (whatsapp-platform-upgrade Step 13).
 * Emitted alongside the existing send/sendMedia events when the
 * composer is in "Note" mode.
 */
export interface ComposerNotePayload {
  text: string;
  mentions: string[];
}

/**
 * Outbound location share (whatsapp-platform-upgrade Step 28).
 * Lat/lng required + optional human-readable name + address.
 * Emitted by the composer's location dialog; the parent shapes
 * this into an attachment + posts via `api.send`.
 */
export interface ComposerLocationPayload {
  latitude: number;
  longitude: number;
  name?: string | null;
  address?: string | null;
}

const MAX_MENTIONS = 5;

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
    SendFromPickerComponent,
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
  /** Step 7: the message currently being quoted, if any. The composer
   *  renders a snippet block above the input; the parent reads this
   *  back on send to attach `reply_to_message_id`. Cleared by Esc or
   *  the X button. */
  @Input() replyingTo: ConversationMessage | null = null;

  /** Step 13: org staff list for the @-mention picker. The parent
   *  (conversations.page) loads this once at mount and passes it
   *  down. Empty when not yet loaded — the picker just renders no
   *  candidates. */
  @Input() staff: UserMini[] = [];

  /** Step 15: WhatsApp 24-hour session window has expired. When true,
   *  the textarea is disabled in Reply mode (note mode is unaffected
   *  — internal notes don't reach the customer). The parent renders
   *  the recovery banner + template picker above the thread. */
  @Input() outOfSession = false;

  /** Step 27b — WhatsApp phone the customer reached us on (read
   *  from the conversation's `received_via_phone_id`). The
   *  Send-From picker uses this as the preferred default so a
   *  reply lands on the same number — operators only need to
   *  override when intentionally switching numbers. */
  @Input() receivedViaPhoneId: string | null = null;

  @Output() readonly send = new EventEmitter<string>();
  @Output() readonly sendMedia = new EventEmitter<ComposerMediaPayload>();
  @Output() readonly sendNote = new EventEmitter<ComposerNotePayload>();
  @Output() readonly sendLocation = new EventEmitter<ComposerLocationPayload>();
  @Output() readonly openInteractive = new EventEmitter<void>();
  @Output() readonly toggleAi = new EventEmitter<boolean>();
  @Output() readonly clearReply = new EventEmitter<void>();

  /** Step 27b — explicit send-from selection. Null when the org
   *  is single-number (picker hidden). Lives on this component
   *  instance, so the choice resets when the compose-bar is
   *  re-created (i.e. when a different conversation is opened). */
  protected readonly sendFromPhoneId = signal<string | null>(null);

  // --- Step 28: outbound location share -------------------------------

  protected readonly locationDialogOpen = signal<boolean>(false);
  protected readonly locationDraft = signal<{
    latitude: string;
    longitude: string;
    name: string;
    address: string;
  }>({ latitude: '', longitude: '', name: '', address: '' });

  protected openLocationDialog(): void {
    this.locationDraft.set({
      latitude: '',
      longitude: '',
      name: '',
      address: '',
    });
    this.locationDialogOpen.set(true);
  }

  protected closeLocationDialog(): void {
    this.locationDialogOpen.set(false);
  }

  protected patchLocation(
    patch: Partial<{ latitude: string; longitude: string; name: string; address: string }>,
  ): void {
    this.locationDraft.update((d) => ({ ...d, ...patch }));
  }

  /** Pull the device's geolocation via the browser API. Best-effort;
   *  any failure (permission denied, no GPS, https-only context)
   *  leaves the form unchanged. */
  protected useMyLocation(): void {
    if (!navigator.geolocation) {
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        this.patchLocation({
          latitude: String(pos.coords.latitude),
          longitude: String(pos.coords.longitude),
        });
      },
      () => {
        // Silent — operator can still type coords manually.
      },
      { enableHighAccuracy: false, timeout: 5_000 },
    );
  }

  protected canSendLocation(): boolean {
    const d = this.locationDraft();
    const lat = Number(d.latitude);
    const lng = Number(d.longitude);
    return (
      Number.isFinite(lat) &&
      Number.isFinite(lng) &&
      lat >= -90 &&
      lat <= 90 &&
      lng >= -180 &&
      lng <= 180
    );
  }

  protected submitLocation(): void {
    if (!this.canSendLocation()) return;
    const d = this.locationDraft();
    this.sendLocation.emit({
      latitude: Number(d.latitude),
      longitude: Number(d.longitude),
      name: d.name.trim() || null,
      address: d.address.trim() || null,
    });
    this.locationDialogOpen.set(false);
  }

  protected onSendFromChange(phoneId: string | null): void {
    this.sendFromPhoneId.set(phoneId);
  }

  /** Read by the parent on `(send)` to attach the phone id to the
   *  outbound API payload. Public so the conversations page can
   *  call it from the (send) handler without subscribing to yet
   *  another output. */
  public currentSendFromPhoneId(): string | null {
    return this.sendFromPhoneId();
  }

  @ViewChild('fileInput') private readonly fileInput?: ElementRef<HTMLInputElement>;
  /** Handle to the textarea for auto-grow. We start it at rows="1"
   *  (~2rem) and expand as the user types up to a cap so long drafts
   *  don't push the compose bar off the screen. */
  @ViewChild('textareaEl') private readonly textareaEl?: ElementRef<HTMLTextAreaElement>;

  /** Max height in px the textarea grows to before it turns into a
   *  scroll surface. Keeps the compose bar bounded so a 40-line paste
   *  can't hide the messages above. */
  private static readonly TEXTAREA_MAX_HEIGHT_PX = 200;

  /** Recompute the textarea's height so it fits its content. Called
   *  after every `text()` mutation (typing, mention-picker rewrite,
   *  template picker, reset-on-send). Uses ``height: auto`` first so
   *  removing lines actually shrinks the box back down. */
  private autoGrowTextarea(): void {
    const el = this.textareaEl?.nativeElement;
    if (!el) return;
    el.style.height = 'auto';
    const next = Math.min(el.scrollHeight, ComposeBarComponent.TEXTAREA_MAX_HEIGHT_PX);
    el.style.height = next + 'px';
  }

  protected readonly text = signal<string>('');
  protected readonly templateError = signal<string | null>(null);

  /** Step 13: composer mode toggle. "reply" sends to the channel as
   *  usual; "note" persists an internal-only annotation. */
  protected readonly mode = signal<'reply' | 'note'>('reply');
  protected readonly MAX_MENTIONS = MAX_MENTIONS;

  /** Mention picker state. Visible when the user just typed `@` at
   *  the end of the current text. `mentionQuery` is the chars typed
   *  after the `@`; the picker filters `staff` by that prefix. */
  protected readonly mentionOpen = signal<boolean>(false);
  protected readonly mentionQuery = signal<string>('');
  /** Resolved mentions for the in-flight note. Each entry is
   *  ``{userId, displayName}`` — we keep both so the chip row can
   *  render without re-resolving from `staff` on every keystroke. */
  protected readonly mentions = signal<Array<{ userId: string; displayName: string }>>([]);

  protected readonly mentionCandidates = computed(() => {
    const q = this.mentionQuery().toLowerCase();
    const chosen = new Set(this.mentions().map((m) => m.userId));
    return this.staff
      .filter((s) => !chosen.has(s.id) && (q.length === 0 || s.full_name.toLowerCase().includes(q)))
      .slice(0, 6);
  });

  protected readonly isNoteMode = computed(() => this.mode() === 'note');

  protected readonly stagedFile = signal<File | null>(null);
  protected readonly stagedType = signal<ComposerAttachmentType | null>(null);
  protected readonly mediaError = signal<string | null>(null);
  protected readonly isDragging = signal(false);

  protected readonly canAttachMedia = computed(() => this.channel === 'whatsapp');
  protected readonly captionsSupported = computed(() => {
    const t = this.stagedType();
    return t === 'image' || t === 'video' || t === 'document';
  });
  protected readonly placeholder = computed(() => {
    if (this.isNoteMode()) {
      return 'Add an internal note — only your team can see it. Type @ to mention.';
    }
    if (this.outOfSession) {
      return 'Session expired — only approved WhatsApp templates can be sent right now.';
    }
    if (!this.stagedFile()) {
      return 'Type a reply or let AI handle it…';
    }
    return this.captionsSupported()
      ? 'Add a caption (optional)…'
      : 'Audio messages don’t support captions';
  });

  /** Step 15 — derived "can free-text" state used by the textarea
   *  disabled-binding + the Send button enabled-binding. Note mode
   *  bypasses the session-window check (notes are internal). */
  protected readonly textareaDisabled = computed(() => {
    if (this.isNoteMode()) return false;
    if (this.outOfSession) return true;
    return !!this.stagedFile() && !this.captionsSupported();
  });

  protected onTextChange(value: string): void {
    this.text.set(value);
    if (this.isNoteMode()) {
      this.refreshMentionPicker(value);
    }
    // Defer until Angular writes the new value to the DOM so
    // ``scrollHeight`` reflects the just-typed content, not the
    // previous frame.
    queueMicrotask(() => this.autoGrowTextarea());
  }

  /** Reads the text buffer, opens the mention picker when the cursor
   *  sits just after an active `@` token (e.g. `Hey @rav` → picker
   *  open with query "rav"). Closes the picker on whitespace after the
   *  `@`. The implementation keeps the rule simple — last @-segment
   *  in the string — because the composer is a single-line-ish
   *  textarea, not a full WYSIWYG editor. */
  private refreshMentionPicker(value: string): void {
    const match = /(?:^|\s)@(\w*)$/.exec(value);
    if (match) {
      this.mentionQuery.set(match[1] || '');
      this.mentionOpen.set(true);
    } else {
      this.mentionOpen.set(false);
      this.mentionQuery.set('');
    }
  }

  protected setMode(mode: 'reply' | 'note'): void {
    if (this.mode() === mode) return;
    this.mode.set(mode);
    // Switching to note mode clears any reply target — a note doesn't
    // carry channel context. Switching back to reply leaves mentions
    // alone (cheap re-toggle).
    if (mode === 'note' && this.replyingTo) {
      this.clearReply.emit();
    }
    if (mode === 'reply') {
      this.mentionOpen.set(false);
    }
  }

  protected pickMention(staff: UserMini): void {
    if (this.mentions().length >= MAX_MENTIONS) return;
    this.mentions.update((arr) => [...arr, { userId: staff.id, displayName: staff.full_name }]);
    // Replace the trailing `@query` token with `@FullName` so the
    // operator sees what they tagged inline with the note text.
    const current = this.text();
    const replaced = current.replace(/(?:^|\s)@(\w*)$/, (match) => {
      const prefix = match.startsWith(' ') ? ' ' : '';
      return `${prefix}@${staff.full_name} `;
    });
    this.text.set(replaced);
    this.mentionOpen.set(false);
    this.mentionQuery.set('');
  }

  protected removeMention(userId: string): void {
    this.mentions.update((arr) => arr.filter((m) => m.userId !== userId));
  }

  protected requestInteractive(): void {
    if (!this.canAttachMedia()) return;
    this.openInteractive.emit();
  }

  protected submit(): void {
    const file = this.stagedFile();
    const type = this.stagedType();
    const trimmed = this.text().trim();

    // Step 13 — Note mode bypasses every channel path. Media + reply
    // affordances are silently ignored when posting a note (the UI
    // hides them already; this is a defensive guard).
    if (this.isNoteMode()) {
      if (!trimmed) return;
      this.sendNote.emit({
        text: trimmed,
        mentions: this.mentions().map((m) => m.userId),
      });
      this.text.set('');
      this.mentions.set([]);
      this.mentionOpen.set(false);
      this.mentionQuery.set('');
      queueMicrotask(() => this.autoGrowTextarea());
      return;
    }

    // Step 15 — refuse free-text + media sends when the WhatsApp
    // session window has expired. The textarea is already disabled
    // for the operator; this is a defence in depth.
    if (this.outOfSession) return;

    if (file && type) {
      const caption = this.captionsSupported() && trimmed ? trimmed : undefined;
      this.sendMedia.emit({ file, type, caption });
      this.clearStaged();
      this.text.set('');
      queueMicrotask(() => this.autoGrowTextarea());
      return;
    }
    if (!trimmed) return;
    this.send.emit(trimmed);
    this.text.set('');
    queueMicrotask(() => this.autoGrowTextarea());
  }

  protected onKey(event: KeyboardEvent): void {
    if (event.key === 'Escape' && this.replyingTo) {
      event.preventDefault();
      this.clearReply.emit();
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.submit();
    }
  }

  protected quotedSnippet(): string {
    const m = this.replyingTo;
    if (!m) return '';
    if (m.text) return m.text;
    const att = (m.attachments ?? []).find((a) => {
      const t = (a as { type?: string }).type;
      return t === 'image' || t === 'video' || t === 'audio' || t === 'document';
    });
    const type = (att as { type?: string } | undefined)?.type;
    switch (type) {
      case 'image':
        return '📷 Photo';
      case 'video':
        return '🎥 Video';
      case 'audio':
        return '🎵 Audio';
      case 'document':
        return '📄 Document';
      default:
        return 'Original message';
    }
  }

  protected dismissReply(): void {
    this.clearReply.emit();
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

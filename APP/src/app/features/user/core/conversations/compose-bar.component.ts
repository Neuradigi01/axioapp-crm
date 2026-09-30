import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  HostListener,
  Input,
  Output,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { EmailTemplateRenderResponse } from '../services/email-templates-api.service';
import { EmailTemplatePickerComponent } from '../shared/email/template-picker.component';
import { SendFromPickerComponent } from '../whatsapp/shared/send-from-picker.component';
import { ConversationMessage, SavedReply } from './conversations-api.service';
import { SavedRepliesManagerComponent } from './saved-replies-manager.component';
import { SavedRepliesStore } from './saved-replies.store';
import { UserMini } from '../shared/services/users-directory.service';

export type ComposerAttachmentType = 'image' | 'video' | 'audio' | 'document';

/** Email reply with attachments (email channel only). */
export interface ComposerEmailPayload {
  text: string;
  files: File[];
}

// Mirror of the backend email-attachment limits (conversations/utils.py).
const MAX_EMAIL_FILES = 10;
const MAX_EMAIL_FILE_BYTES = 10 * 1024 * 1024;
const MAX_EMAIL_TOTAL_BYTES = 18 * 1024 * 1024;

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

/** Per-conversation unsent drafts live in sessionStorage so switching
 *  threads (or refreshing the tab) never loses — or leaks — typed text.
 *  Private-mode browsers throw on access; drafts are then in-memory
 *  only for the lifetime of the component. */
const DRAFT_KEY_PREFIX = 'conversations:draft:';

function readDraft(conversationId: string): string {
  try {
    return sessionStorage.getItem(DRAFT_KEY_PREFIX + conversationId) ?? '';
  } catch {
    return '';
  }
}

function writeDraft(conversationId: string, text: string): void {
  try {
    if (text.trim()) sessionStorage.setItem(DRAFT_KEY_PREFIX + conversationId, text);
    else sessionStorage.removeItem(DRAFT_KEY_PREFIX + conversationId);
  } catch {
    // Best-effort; failure is silent.
  }
}

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
    SavedRepliesManagerComponent,
  ],
  templateUrl: './compose-bar.component.html',
})
export class ComposeBarComponent {
  protected readonly savedReplies = inject(SavedRepliesStore);

  // --- Saved replies ---------------------------------------------------

  /** `/shortcut` picker — open while the whole draft is a single
   *  `/token` (e.g. `/pri`); Enter / Tab inserts the highlighted reply. */
  protected readonly slashQuery = signal<string | null>(null);
  protected readonly slashIndex = signal(0);
  protected readonly slashCandidates = computed(() => {
    const q = this.slashQuery();
    return q === null ? [] : this.savedReplies.search(q, 6);
  });
  /** Zap-button menu in the action row. */
  protected readonly repliesMenuOpen = signal(false);
  protected readonly repliesMenuQuery = signal('');
  protected readonly repliesMenuItems = computed(() =>
    this.savedReplies.search(this.repliesMenuQuery(), 8),
  );
  protected readonly managerOpen = signal(false);
  @ViewChild(SavedRepliesManagerComponent) private readonly manager?: SavedRepliesManagerComponent;

  protected toggleRepliesMenu(): void {
    this.savedReplies.ensureLoaded();
    this.repliesMenuQuery.set('');
    this.repliesMenuOpen.update((v) => !v);
  }

  protected insertSavedReply(reply: SavedReply): void {
    this.repliesMenuOpen.set(false);
    this.slashQuery.set(null);
    this.setText(reply.body);
    this.focusInput();
  }

  protected openManager(prefillFromDraft = false): void {
    this.repliesMenuOpen.set(false);
    this.managerOpen.set(true);
    const draft = this.text().trim();
    if (prefillFromDraft && draft) queueMicrotask(() => this.manager?.prefill(draft));
  }

  private refreshSlashPicker(value: string): void {
    const match = /^\/([\w-]*)$/.exec(value);
    if (match) {
      this.savedReplies.ensureLoaded();
      this.slashQuery.set(match[1].toLowerCase());
      this.slashIndex.set(0);
    } else {
      this.slashQuery.set(null);
    }
  }

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

  /** True while an AI draft is being generated (button spinner). */
  @Input() aiBusy = false;
  /** Operator asked AI to draft the next reply. */
  @Output() readonly aiSuggest = new EventEmitter<void>();

  /** Conversation this composer is bound to. The page keeps a single
   *  composer instance alive across thread switches, so every piece of
   *  per-thread state (typed text, staged file, note mode, mentions,
   *  Send-From choice, open dialogs) is reset here — otherwise a reply
   *  typed for one customer could be sent to the next thread opened.
   *  Typed text is parked as a draft and restored on return. */
  @Input() set conversationId(id: string | null) {
    if (id === this.boundConversationId) return;
    if (this.boundConversationId) writeDraft(this.boundConversationId, this.text());
    this.boundConversationId = id;
    this.resetForConversation(id);
  }
  private boundConversationId: string | null = null;

  @Output() readonly send = new EventEmitter<string>();
  @Output() readonly sendMedia = new EventEmitter<ComposerMediaPayload>();
  @Output() readonly sendEmailWithFiles = new EventEmitter<ComposerEmailPayload>();
  @Output() readonly sendNote = new EventEmitter<ComposerNotePayload>();
  @Output() readonly sendLocation = new EventEmitter<ComposerLocationPayload>();
  @Output() readonly openInteractive = new EventEmitter<void>();
  @Output() readonly toggleAi = new EventEmitter<boolean>();
  @Output() readonly clearReply = new EventEmitter<void>();

  /** Step 27b — explicit send-from selection. Null when the org
   *  is single-number (picker hidden). Reset on every conversation
   *  switch (see `conversationId`) so the picker falls back to the
   *  number the new thread's customer reached us on. */
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

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (this.locationDialogOpen()) this.closeLocationDialog();
    this.repliesMenuOpen.set(false);
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
  /** Keyboard-highlighted row in the mention picker (↑/↓ + Enter/Tab). */
  protected readonly mentionIndex = signal<number>(0);
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
  /** Email replies accept any file type (multiple files). */
  protected readonly isEmail = computed(() => this.channel === 'email');
  protected readonly canAttach = computed(() => this.canAttachMedia() || this.isEmail());
  protected readonly emailFiles = signal<File[]>([]);
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
    this.setText(value);
    this.refreshSlashPicker(value);
    if (this.isNoteMode()) {
      this.refreshMentionPicker(value);
    }
  }

  /** Single write path for the textarea buffer: keeps the per-thread
   *  draft in sync and re-fits the textarea height. The resize is
   *  deferred until Angular writes the new value to the DOM so
   *  ``scrollHeight`` reflects the new content, not the previous frame. */
  private setText(value: string): void {
    this.text.set(value);
    if (this.boundConversationId) writeDraft(this.boundConversationId, value);
    queueMicrotask(() => this.autoGrowTextarea());
  }

  /** Wipe all per-thread state and load the target thread's draft. */
  private resetForConversation(id: string | null): void {
    this.mode.set('reply');
    this.mentions.set([]);
    this.mentionOpen.set(false);
    this.mentionQuery.set('');
    this.mentionIndex.set(0);
    this.clearStaged();
    this.emailFiles.set([]);
    this.isDragging.set(false);
    this.sendFromPhoneId.set(null);
    this.templateError.set(null);
    this.locationDialogOpen.set(false);
    this.slashQuery.set(null);
    this.repliesMenuOpen.set(false);
    this.text.set(id ? readDraft(id) : '');
    queueMicrotask(() => this.autoGrowTextarea());
  }

  /** Called by the page when a send fails so the operator's message is
   *  never lost: the text goes back into the composer (unless they have
   *  already started typing something new) and focus returns to it. */
  public restoreText(conversationId: string, text: string): void {
    if (conversationId !== this.boundConversationId) {
      if (!readDraft(conversationId).trim()) writeDraft(conversationId, text);
      return;
    }
    if (this.text().trim()) return;
    this.setText(text);
    this.focusInput();
  }

  /** Put an AI-drafted reply in the composer for the operator to review
   *  and edit — never sent automatically. Switches to reply mode. */
  public applyAiDraft(conversationId: string, text: string): void {
    if (conversationId !== this.boundConversationId) return;
    this.setMode('reply');
    this.setText(text);
    this.focusInput();
  }

  /** Focus the textarea — used by the page's `r` / `n` shortcuts. */
  public focusInput(mode?: 'reply' | 'note'): void {
    if (mode) this.setMode(mode);
    queueMicrotask(() => this.textareaEl?.nativeElement.focus());
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
      this.mentionIndex.set(0);
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
    this.setText(replaced);
    this.mentionOpen.set(false);
    this.mentionQuery.set('');
    this.focusInput();
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
      this.setText('');
      this.mentions.set([]);
      this.mentionOpen.set(false);
      this.mentionQuery.set('');
      return;
    }

    // Step 15 — refuse free-text + media sends when the WhatsApp
    // session window has expired. The textarea is already disabled
    // for the operator; this is a defence in depth.
    if (this.outOfSession) return;

    const emailFiles = this.emailFiles();
    if (this.isEmail() && emailFiles.length > 0) {
      if (!trimmed) {
        this.mediaError.set('Add a message to go with the attachments.');
        return;
      }
      this.sendEmailWithFiles.emit({ text: trimmed, files: emailFiles });
      this.emailFiles.set([]);
      this.mediaError.set(null);
      this.setText('');
      return;
    }

    if (file && type) {
      const caption = this.captionsSupported() && trimmed ? trimmed : undefined;
      this.sendMedia.emit({ file, type, caption });
      this.clearStaged();
      this.setText('');
      return;
    }
    if (!trimmed) return;
    this.send.emit(trimmed);
    this.setText('');
  }

  protected onKey(event: KeyboardEvent): void {
    // IME composition (Hindi / CJK keyboards) uses Enter to commit the
    // candidate word — never treat that as "send".
    if (event.isComposing) return;

    const replies = this.slashCandidates();
    if (this.slashQuery() !== null && replies.length > 0) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const step = event.key === 'ArrowDown' ? 1 : -1;
        this.slashIndex.update((i) => (i + step + replies.length) % replies.length);
        return;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault();
        this.insertSavedReply(replies[Math.min(this.slashIndex(), replies.length - 1)]);
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        this.slashQuery.set(null);
        return;
      }
    }

    if (this.mentionOpen() && this.isNoteMode()) {
      const candidates = this.mentionCandidates();
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (candidates.length === 0) return;
        const step = event.key === 'ArrowDown' ? 1 : -1;
        this.mentionIndex.update((i) => (i + step + candidates.length) % candidates.length);
        return;
      }
      if ((event.key === 'Enter' || event.key === 'Tab') && candidates.length > 0) {
        event.preventDefault();
        this.pickMention(candidates[Math.min(this.mentionIndex(), candidates.length - 1)]);
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        this.mentionOpen.set(false);
        return;
      }
    }

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
    this.setText(resp.body_text || resp.body_html);
  }

  protected onTemplateError(message: string): void {
    this.templateError.set(message);
  }

  protected dismissTemplateError(): void {
    this.templateError.set(null);
  }

  // --- Media attach --------------------------------------------------

  protected openFilePicker(): void {
    if (!this.canAttach()) return;
    this.fileInput?.nativeElement.click();
  }

  protected onFilePicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (this.isEmail()) {
      this.stageEmailFiles(Array.from(input.files ?? []));
      input.value = '';
      return;
    }
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
    if (!this.canAttach()) return;
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
    if (!this.canAttach()) return;
    if (this.isEmail()) {
      this.stageEmailFiles(Array.from(event.dataTransfer?.files ?? []));
      return;
    }
    const file = event.dataTransfer?.files?.[0] ?? null;
    if (file) {
      this.stageFile(file);
    }
  }

  /** Add files to the email attachment list, enforcing the same limits
   *  as the backend so the operator gets instant feedback. */
  private stageEmailFiles(files: File[]): void {
    if (files.length === 0) return;
    const next = [...this.emailFiles(), ...files];
    if (next.length > MAX_EMAIL_FILES) {
      this.mediaError.set(`Attach at most ${MAX_EMAIL_FILES} files per email.`);
      return;
    }
    const tooBig = files.find((f) => f.size > MAX_EMAIL_FILE_BYTES);
    if (tooBig) {
      this.mediaError.set(`"${tooBig.name}" is larger than 10 MB.`);
      return;
    }
    if (files.some((f) => f.size === 0)) {
      this.mediaError.set('Empty files cannot be attached.');
      return;
    }
    const total = next.reduce((sum, f) => sum + f.size, 0);
    if (total > MAX_EMAIL_TOTAL_BYTES) {
      this.mediaError.set('Attachments exceed 18 MB in total — email providers would reject it.');
      return;
    }
    this.mediaError.set(null);
    this.emailFiles.set(next);
  }

  protected removeEmailFile(index: number): void {
    this.emailFiles.update((files) => files.filter((_, i) => i !== index));
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

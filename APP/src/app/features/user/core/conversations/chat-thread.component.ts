import {
  AfterViewChecked,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import {
  Conversation,
  ConversationDetail,
  ConversationMessage,
  ConversationStatus,
  ConversationTagRef,
  MessageReaction,
} from './conversations-api.service';
import { ReactionPickerComponent } from './reaction-picker.component';
import { TagChipComponent } from './tag-chip.component';
import { TagManagerComponent } from './tag-manager.component';
import { AttributionChipComponent } from './header/attribution-chip.component';
import { ConversationBlockNumberActionComponent } from './header/block-number-action.component';
import { ConversationExportButtonComponent } from './header/export-button.component';
import { LocationAttachment, LocationBubbleComponent } from './thread/location-bubble.component';
import { StickerAttachment, StickerBubbleComponent } from './thread/sticker-bubble.component';
import { VCardAttachment, VCardBubbleComponent } from './thread/vcard-bubble.component';
import { StaffListItem } from '../staff/staff-api.service';
import { OwnerColor, ownerColor, staffInitials } from '../shared/owner-color.util';
import { FurnitureAuthService } from '../auth/auth.service';
import { environment } from '../../../../../environments/environment';

/** mailgun-inbound Step 5 attachment shape (email path):
 *  ``{filename, size, content_type, storage_key, storage_backend}``.
 *  WhatsApp / Meta attachments use a different shape keyed on
 *  ``type`` — the render helpers below discriminate purely on the
 *  presence of ``storage_key`` so email files render as a
 *  downloadable link and WA media rides its existing counter.
 */
interface EmailAttachmentMeta {
  filename: string;
  size?: number;
  content_type?: string;
  storage_key: string;
  storage_backend?: string;
}

/**
 * Chat thread — renders bubbles, auto-scrolls to bottom on new
 * messages. The conversation header shows the external_id + channel +
 * a state-aware AI pill that reflects the real ``ai_active`` /
 * ``ai_paused`` truth (bound-assistant + takeover state) rather than
 * the legacy per-conversation ``ai_handling`` flag. Clicking the pill
 * emits ``takeoverAi`` / ``resumeAiOut`` — same handlers the banner's
 * Take Over / Return to AI buttons drive.
 *
 * Optimistic outbound messages have ids that start with `tmp-`; we
 * grey them slightly so the user can tell the wire hasn't ack'd yet.
 */
@Component({
  selector: 'app-chat-thread',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LucideAngularModule,
    ReactionPickerComponent,
    TagChipComponent,
    TagManagerComponent,
    ConversationBlockNumberActionComponent,
    ConversationExportButtonComponent,
    AttributionChipComponent,
    LocationBubbleComponent,
    StickerBubbleComponent,
    VCardBubbleComponent,
  ],
  templateUrl: './chat-thread.component.html',
  host: { class: 'flex min-h-0 flex-1 flex-col' },
})
export class ChatThreadComponent implements AfterViewChecked, OnChanges {
  private readonly auth = inject(FurnitureAuthService);
  private readonly http = inject(HttpClient);

  @Input({ required: true }) conversation!: Conversation;
  @Input() detail: ConversationDetail | null = null;
  @Input() loading = false;
  @Input() staffById: Map<string, StaffListItem> = new Map();

  /** tasks/ai-assistants-omnichannel Step 4 — user clicked the Take
   *  Over button on the AI-status banner. The page owns the POST +
   *  optimistic-flip semantics. Emitted only when ``ai_paused === false``
   *  is visible in the banner. */
  @Output() readonly takeoverAi = new EventEmitter<void>();

  /** Step 4 — user clicked Return to AI (banner in the paused state).
   *  Confirmation dialog lives on the page side so this stays a bare
   *  emit — one click, one event. */
  @Output() readonly resumeAiOut = new EventEmitter<void>();

  /** Fires when the user clicks the assignee pill. The page parent owns
   * the modal + PATCH. We emit a bare event because the parent already
   * knows which conversation is selected via `selectedConversation()`. */
  @Output() readonly reassign = new EventEmitter<void>();

  /** Step 7: user clicked Reply on a message — parent puts the composer
   *  into "replying-to" mode with the quoted snippet. */
  @Output() readonly replyTo = new EventEmitter<ConversationMessage>();

  /** Step 7: user picked a reaction emoji (or null to remove). */
  @Output() readonly react = new EventEmitter<{
    messageId: string;
    emoji: string | null;
  }>();

  /** Which message currently has its reaction picker open. Null = none.
   *  Toggled by the React button on the hover action bar. */
  protected readonly pickerOpenFor = signal<string | null>(null);

  /** Step 14 — visibility of the tag-manager dropdown on the
   *  conversation header. */
  protected readonly tagManagerOpen = signal<boolean>(false);

  /** Step 14 — emitted when the tag list on the active conversation
   *  changes (assign / unassign / create). The page updates the
   *  conversation row in its `items` list + the detail. */
  @Output() readonly tagsChanged = new EventEmitter<ConversationTagRef[]>();

  /** J.16 fix — the user picked a new status from the header status
   *  menu (open / snoozed / closed). Parent owns the PATCH; header
   *  just surfaces the choice. Snoozed conversations get an inbound-
   *  wake in ``receive_webhook``; closed ones stay closed until the
   *  operator reopens them explicitly. */
  @Output() readonly statusChange = new EventEmitter<ConversationStatus>();

  /** Header status-menu open flag — flipped by the pill click. */
  protected readonly statusMenuOpen = signal<boolean>(false);

  protected toggleStatusMenu(): void {
    this.statusMenuOpen.update((v) => !v);
  }

  protected closeStatusMenu(): void {
    this.statusMenuOpen.set(false);
  }

  protected pickStatus(next: ConversationStatus): void {
    this.closeStatusMenu();
    if (next === this.conversation.status) return;
    this.statusChange.emit(next);
  }

  /** Human label for the header pill — used for the trigger button
   *  and read out in the menu items. */
  protected readonly statusLabel: Record<ConversationStatus, string> = {
    open: 'Open',
    snoozed: 'Snoozed',
    closed: 'Closed',
  };

  /** Menu options in fixed order so the DOM structure is stable. */
  protected readonly statusOptions: readonly ConversationStatus[] = [
    'open',
    'snoozed',
    'closed',
  ] as const;

  protected toggleTagManager(): void {
    this.tagManagerOpen.update((v) => !v);
  }

  protected closeTagManager(): void {
    this.tagManagerOpen.set(false);
  }

  protected onTagsChanged(tags: ConversationTagRef[]): void {
    this.tagsChanged.emit(tags);
  }

  /** Permission gate for the reassign click target. Mirrors the
   * backend rule in `service.ensure_can_assign_conversation`:
   *   - Owner / Admin (`conversations.assign_others`) can always
   *     reassign.
   *   - The current assignee can transfer their own chat.
   *   - Everyone else (including Employees viewing an unassigned
   *     chat) can only be assigned *to* themselves via take-over from
   *     AI / send-outbound implicit claim; the assignee dropdown
   *     stays hidden. */
  protected readonly canReassign = computed(() => {
    if (this.auth.hasPermission('conversations.assign_others')) return true;
    const me = this.auth.currentUserId();
    return !!me && this.conversation?.assigned_to_id === me;
  });

  /** Write gate for reply / react / tag / mark-read on the current
   * thread. Mirrors the backend `ensure_can_write_conversation` rule
   * (locked 2026-09-10):
   *   - Chat unassigned → any writer can jump in. Sending a reply
   *     auto-claims the chat for the sender (backend does the same
   *     via `send_outbound` / `send_email_reply`).
   *   - Caller is the current assignee → allowed.
   *   - Owner / Admin (`conversations.assign_others`) → always
   *     allowed.
   *   - Anyone else viewing an assigned chat → view-only.
   *
   * When false the template renders the thread in view-only mode:
   * compose bar hidden, reply/react/tag hidden, banner explains why. */
  protected readonly canInteract = computed(() => {
    if (this.auth.hasPermission('conversations.assign_others')) return true;
    const owner = this.conversation?.assigned_to_id ?? null;
    if (owner === null) return true;
    const me = this.auth.currentUserId();
    return !!me && owner === me;
  });

  /** Take-Over-from-AI button gate. Locked to Owner / Admin only —
   * Employees never see the button (product rule 2026-09-10: only
   * Owner/Admin can explicitly take over). Employees can still
   * work an unassigned AI-handling chat by just replying (send
   * auto-claims + auto-pauses via ``send_outbound``); the explicit
   * "Take Over" motion is an admin-only supervisor action. */
  protected readonly canTakeOver = computed(() =>
    this.auth.hasPermission('conversations.assign_others'),
  );

  /** Return-to-AI gate. Only the current holder (assignee) OR an
   * Owner / Admin can hand a paused chat back to AI. Matches the
   * backend rule in ``resume_ai`` (403 ``not_holder`` otherwise). */
  protected readonly canReturnToAi = computed(() => {
    if (this.auth.hasPermission('conversations.assign_others')) return true;
    const holder = this.conversation?.ai_paused_by_user_id ?? null;
    const me = this.auth.currentUserId();
    return !!me && holder === me;
  });

  /** Name of the current assignee — used by the view-only banner. */
  protected readonly assigneeDisplayName = computed<string | null>(() => {
    const owner = this.conversation?.assigned_to_id;
    if (!owner) return null;
    return this.staffById.get(owner)?.full_name ?? 'another user';
  });

  @ViewChild('scrollHost') protected scrollHost?: ElementRef<HTMLDivElement>;

  private lastMessageCount = 0;
  // Tracked separately from the count so that switching between two
  // conversations that happen to have the same message count still
  // fires a scroll-to-bottom (count would look unchanged otherwise —
  // the operator would land halfway up the new thread and have to
  // scroll down manually to see the newest bubble).
  private lastConversationId: string | null = null;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['conversation'] && this.conversation?.id !== this.lastConversationId) {
      this.lastConversationId = this.conversation?.id ?? null;
      // Force the next ngAfterViewChecked to treat this as a "first
      // render" — count comparison will always see a change and scroll
      // to bottom on the freshly-loaded thread.
      this.lastMessageCount = -1;
    }
  }

  ngAfterViewChecked(): void {
    const count = this.detail?.messages.length ?? 0;
    if (count !== this.lastMessageCount && this.scrollHost) {
      const el = this.scrollHost.nativeElement;
      // Use rAF so the layout has applied before we measure scrollHeight.
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
      });
      this.lastMessageCount = count;
    }
  }

  protected formatTime(iso: string | null): string {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate();
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (sameDay) return time;
    // Older than today: prepend the short date so an operator can
    // distinguish "14:32 today" from "14:32 last Tuesday" at a glance.
    const date = d.toLocaleDateString([], { day: '2-digit', month: 'short' });
    return `${date} · ${time}`;
  }

  protected isPending(m: ConversationMessage): boolean {
    return m.id.startsWith('tmp-');
  }

  /**
   * WhatsApp-style tick state for outbound messages (Step 3.5.13).
   *
   *   `read`      → ✓✓ blue   — Meta `status='read'`
   *   `delivered` → ✓✓ grey   — Meta `status='delivered'`
   *   `sent`      → ✓ grey    — outbound POST returned a message id
   *   `pending`   → clock     — local optimistic row, no `sent_at` yet
   *
   * Inbound messages have no tick state — caller checks `direction`
   * before rendering. Other channels (SMS/email) currently have no
   * delivery tracking; for them only `sent` shows after dispatch.
   */
  protected tickState(m: ConversationMessage): 'read' | 'delivered' | 'sent' | 'pending' {
    if (m.read_at) return 'read';
    if (m.delivered_at) return 'delivered';
    if (m.sent_at) return 'sent';
    return 'pending';
  }

  // --- AI takeover banner (omnichannel Step 4) ---------------------

  /** Show the takeover banner only when AI is genuinely part of this
   *  conversation — either currently answering (``ai_active``) or
   *  paused because a human took over (``ai_paused``). The old
   *  fallback that showed the banner on every AI-capable channel
   *  (whatsapp/email/ai_widget) lied when no assistant was actually
   *  bound: the header would read "Needs Human" and the banner
   *  underneath would claim "AI is handling this conversation". */
  protected showTakeoverBanner(): boolean {
    return !!this.conversation.ai_paused || !!this.conversation.ai_active;
  }

  /** Display name of whoever currently holds the paused conversation.
   *  Reuses the ``staffById`` map the header already consumes; falls
   *  back to a generic label so historical / soft-deleted holders
   *  never render as an empty string. */
  protected pausedHolderName(): string {
    const holderId = this.conversation.ai_paused_by_user_id;
    if (!holderId) return 'A team member';
    return this.staffById.get(holderId)?.full_name ?? 'A team member';
  }

  protected onTakeoverClick(): void {
    this.takeoverAi.emit();
  }

  protected onResumeClick(): void {
    this.resumeAiOut.emit();
  }

  /** Two-letter initials for a staff member referenced by user id.
   * Returns `·` for null (unassigned thread header) and `?` when the
   * id doesn't resolve (e.g. soft-deleted user). */
  protected staffInitialsFor(userId: string | null): string {
    if (!userId) return '·';
    const staff = this.staffById.get(userId);
    return staff ? staffInitials(staff.full_name) : '?';
  }

  /** Full display name for the tooltip / pill label. */
  protected staffNameFor(userId: string | null): string {
    if (!userId) return 'Unassigned';
    return this.staffById.get(userId)?.full_name ?? 'Unknown user';
  }

  /** Deterministic colour triple — same user always gets the same
   * colour across leads, appointments, conversations. */
  protected staffColorFor(userId: string | null): OwnerColor {
    return ownerColor(userId);
  }

  // --- Interactive (whatsapp-platform-upgrade Step 6) --------------

  protected interactiveKind(m: ConversationMessage): 'reply_buttons' | 'cta_url' | 'list' | null {
    const p = m.interactive_payload;
    if (!p || typeof p !== 'object') return null;
    const k = (p as { kind?: string }).kind;
    return k === 'reply_buttons' || k === 'cta_url' || k === 'list' ? k : null;
  }

  protected interactiveButtons(m: ConversationMessage): Array<{ id: string; title: string }> {
    const p = m.interactive_payload as { buttons?: Array<{ id?: string; title?: string }> } | null;
    if (!p?.buttons) return [];
    return p.buttons
      .filter((b) => typeof b.id === 'string' && typeof b.title === 'string')
      .map((b) => ({ id: b.id as string, title: b.title as string }));
  }

  protected interactiveCta(m: ConversationMessage): { button_text: string; url: string } | null {
    const p = m.interactive_payload as { button_text?: string; url?: string } | null;
    if (!p?.button_text || !p?.url) return null;
    return { button_text: p.button_text, url: p.url };
  }

  protected interactiveListSections(m: ConversationMessage): Array<{
    title: string;
    rows: Array<{ id: string; title: string; description?: string }>;
  }> {
    const p = m.interactive_payload as {
      sections?: Array<{
        title?: string;
        rows?: Array<{
          id?: string;
          title?: string;
          description?: string;
        }>;
      }>;
    } | null;
    if (!p?.sections) return [];
    return p.sections.map((s) => ({
      title: s.title ?? '',
      rows: (s.rows ?? [])
        .filter((r) => typeof r.id === 'string' && typeof r.title === 'string')
        .map((r) => ({
          id: r.id as string,
          title: r.title as string,
          description: r.description,
        })),
    }));
  }

  /** Pull the inbound reply-attribution shape `parse_webhook` adds
   *  to `attachments[]` when Meta delivers a button_reply / list_reply
   *  event. Returns null when the message isn't a reply. */
  protected replyAttribution(
    m: ConversationMessage,
  ): { title: string; kind: 'button' | 'list' } | null {
    for (const att of m.attachments ?? []) {
      const a = att as {
        type?: string;
        reply_kind?: string;
        reply_to_title?: string;
      };
      if (
        a.type === 'reply' &&
        (a.reply_kind === 'button' || a.reply_kind === 'list') &&
        typeof a.reply_to_title === 'string'
      ) {
        return { title: a.reply_to_title, kind: a.reply_kind };
      }
    }
    return null;
  }

  /** True when the attachment list has a real media reference
   *  (image/video/audio/document) — Step-5's attachments. The Step-6
   *  reply attribution lives in the same array but should NOT be
   *  counted as a media attachment. */
  protected mediaAttachmentCount(m: ConversationMessage): number {
    return (m.attachments ?? []).filter((att) => {
      const t = (att as { type?: string }).type;
      return t === 'image' || t === 'video' || t === 'audio' || t === 'document';
    }).length;
  }

  /** Step 28 — pluck the first `location` attachment, or null.
   *  The bubble renders only when present so location-less
   *  messages don't paint an empty card. */
  protected locationAttachment(m: ConversationMessage): LocationAttachment | null {
    const found = (m.attachments ?? []).find(
      (att) => (att as { type?: string }).type === 'location',
    );
    return found ? (found as unknown as LocationAttachment) : null;
  }

  /** Step 28 — first `contacts` (vCard) attachment, or null. */
  protected vcardAttachment(m: ConversationMessage): VCardAttachment | null {
    const found = (m.attachments ?? []).find(
      (att) => (att as { type?: string }).type === 'contacts',
    );
    return found ? (found as unknown as VCardAttachment) : null;
  }

  /** Step 28 — first `sticker` attachment, or null. */
  protected stickerAttachment(m: ConversationMessage): StickerAttachment | null {
    const found = (m.attachments ?? []).find(
      (att) => (att as { type?: string }).type === 'sticker',
    );
    return found ? (found as unknown as StickerAttachment) : null;
  }

  /** mailgun-inbound Step 5 — pluck email-shaped attachments
   *  (those carrying a ``storage_key`` field). WhatsApp / Meta
   *  attachments never have ``storage_key`` so they're naturally
   *  excluded and continue to ride their existing render path. */
  protected emailAttachments(m: ConversationMessage): EmailAttachmentMeta[] {
    const out: EmailAttachmentMeta[] = [];
    for (const att of m.attachments ?? []) {
      const raw = att as unknown as {
        storage_key?: unknown;
        filename?: unknown;
        size?: unknown;
        content_type?: unknown;
        storage_backend?: unknown;
      };
      if (typeof raw.storage_key === 'string' && typeof raw.filename === 'string') {
        out.push({
          filename: raw.filename,
          storage_key: raw.storage_key,
          size: typeof raw.size === 'number' ? raw.size : undefined,
          content_type: typeof raw.content_type === 'string' ? raw.content_type : undefined,
          storage_backend:
            typeof raw.storage_backend === 'string' ? raw.storage_backend : undefined,
        });
      }
    }
    return out;
  }

  /** Compose the auth-gated download URL for one email attachment.
   *  Server enforces org isolation + Content-Disposition: attachment
   *  regardless of MIME (Attacker H3). */
  protected emailAttachmentUrl(m: ConversationMessage, att: EmailAttachmentMeta): string {
    return `${environment.apiBaseUrl}/messages/${m.id}/attachments/${att.storage_key}`;
  }

  /** Fetch the attachment via HttpClient so the auth interceptor
   *  attaches the JWT header (native ``<a href>`` clicks don't carry
   *  the Authorization header and get 401'd by the server). Streams
   *  the response into a Blob, hands it to a hidden ``<a download>``,
   *  then revokes the object URL. */
  protected downloadEmailAttachment(m: ConversationMessage, att: EmailAttachmentMeta): void {
    const url = this.emailAttachmentUrl(m, att);
    this.http.get(url, { responseType: 'blob' }).subscribe({
      next: (blob) => {
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = att.filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(objectUrl);
      },
    });
  }

  /** Compact size label — "42 KB" / "3 MB" — for the download link
   *  hover title. Missing / zero size falls back to no suffix. */
  protected formatAttachmentSize(bytes: number | undefined): string {
    if (!bytes || bytes <= 0) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  // --- Reply / quote / reactions (Step 7) ----------------------------

  /** Look up the message being quoted in the in-memory thread cache.
   *  Cross-pagination quotes fall back to null — the bubble renders
   *  "Original message" without the body preview. */
  protected quotedMessage(m: ConversationMessage): ConversationMessage | null {
    if (!m.reply_to_message_id || !this.detail) return null;
    return this.detail.messages.find((x) => x.id === m.reply_to_message_id) ?? null;
  }

  /** Short preview for a quoted block — uses the original's text when
   *  available, else the first media attachment's type emoji ("📷
   *  Photo" / "🎥 Video" / etc.) per the spec's smoke point 7. */
  protected quotedPreview(target: ConversationMessage | null): string {
    if (!target) return 'Original message';
    if (target.text) return target.text;
    const att = (target.attachments ?? []).find((a) => {
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

  /** Aggregate the reactions list into `{emoji → count}` for the badge
   *  row. Order preserved by first-seen so the row stays stable across
   *  re-renders. */
  protected groupedReactions(m: ConversationMessage): Array<{ emoji: string; count: number }> {
    const counts = new Map<string, number>();
    for (const r of m.reactions ?? []) {
      counts.set(r.emoji, (counts.get(r.emoji) ?? 0) + 1);
    }
    return Array.from(counts, ([emoji, count]) => ({ emoji, count }));
  }

  /** The current user's reaction on a message, if any — used by the
   *  picker to highlight the active one and to flip a re-tap into a
   *  remove. */
  protected myReaction(m: ConversationMessage): string | null {
    const me = this.auth.currentUserId();
    if (!me) return null;
    const mine = (m.reactions ?? []).find((r: MessageReaction) => r.actor === me);
    return mine?.emoji ?? null;
  }

  protected openPicker(messageId: string): void {
    this.pickerOpenFor.update((cur) => (cur === messageId ? null : messageId));
  }

  protected closePicker(): void {
    this.pickerOpenFor.set(null);
  }

  protected pickReaction(messageId: string, emoji: string | null): void {
    this.closePicker();
    this.react.emit({ messageId, emoji });
  }

  protected onReplyClick(m: ConversationMessage): void {
    this.replyTo.emit(m);
  }

  protected async copyText(m: ConversationMessage): Promise<void> {
    const text = m.text ?? '';
    if (!text || typeof navigator?.clipboard?.writeText !== 'function') {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Best-effort — clipboard permission failures are silent.
    }
  }
}

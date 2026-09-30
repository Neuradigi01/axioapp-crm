import {
  AfterViewChecked,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  HostListener,
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
  MessageReaction,
} from './conversations-api.service';
import { ReactionPickerComponent } from './reaction-picker.component';
import { AttributionChipComponent } from './header/attribution-chip.component';
import { LocationAttachment, LocationBubbleComponent } from './thread/location-bubble.component';
import { MediaAttachment, MediaBubbleComponent } from './thread/media-bubble.component';
import { VCardAttachment, VCardBubbleComponent } from './thread/vcard-bubble.component';
import { UserMini } from '../shared/services/users-directory.service';
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
 * Strip the Gmail/Outlook reply-quote block from an inbound email body.
 * Cuts the text at whichever comes first:
 *   - a line starting with ``>`` (Gmail wraps the included message with
 *     ``> `` per RFC 3676)
 *   - an "On <date/time> <name> <email> wrote:" attribution (may wrap
 *     across two lines when Gmail hits its 76-char soft wrap)
 *   - an Outlook / plain-text divider like ``-----Original Message-----``
 *     or ``-----Forwarded message-----``
 * Trailing blank lines from what remains are collapsed so the bubble
 * doesn't render whitespace where the quote used to be.
 */
function stripEmailQuote(text: string): string {
  const lines = text.split(/\r?\n/);
  let cutAt = -1;
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (/^>/.test(trimmed)) {
      cutAt = i;
      break;
    }
    if (/^-{2,}\s*(Original|Forwarded)\s+Message\s*-{2,}$/i.test(trimmed)) {
      cutAt = i;
      break;
    }
    if (/^On\b.+\bwrote:\s*$/i.test(trimmed)) {
      cutAt = i;
      break;
    }
    // Gmail sometimes soft-wraps the attribution across two lines
    // (attribution on line N, bare ``wrote:`` on line N+1).
    if (/^On\b/i.test(trimmed)) {
      const combined = (trimmed + ' ' + (lines[i + 1] ?? '').trim()).trim();
      if (/^On\b.+\bwrote:\s*$/i.test(combined)) {
        cutAt = i;
        break;
      }
    }
  }
  if (cutAt < 0) return text;
  const kept = lines.slice(0, cutAt);
  while (kept.length && !kept[kept.length - 1].trim()) kept.pop();
  return kept.join('\n');
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
    AttributionChipComponent,
    LocationBubbleComponent,
    MediaBubbleComponent,
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
  @Input() staffById: Map<string, UserMini> = new Map();

  /** Counterparty label to render in the header. When the parent page
   *  can resolve the linked contact's current phone (see
   *  ``selectedContactHandle`` on the page) it passes that here so
   *  post-edit "+91" prefixes show even on legacy rows whose stored
   *  ``external_id`` snapshot went stale. Falls back to
   *  ``conversation.external_id`` when null. */
  @Input() displayHandle: string | null = null;

  /** Linked contact's full name (when the conversation is joined to a
   *  contact). Rendered as the primary line in the thread header; the
   *  phone / email handle drops to the secondary line beneath it so
   *  the operator sees who they're talking to before what channel it
   *  came in on. Null when no contact is linked — in that case the
   *  handle is promoted back to the primary line. */
  @Input() contactName: string | null = null;

  /** tasks/ai-assistants-omnichannel Step 4 — user clicked the Take
   *  Over button on the AI-status banner. The page owns the POST +
   *  optimistic-flip semantics. Emitted only when ``ai_paused === false``
   *  is visible in the banner. */
  @Output() readonly takeoverAi = new EventEmitter<void>();

  /** Step 4 — user clicked Return to AI (banner in the paused state).
   *  Confirmation dialog lives on the page side so this stays a bare
   *  emit — one click, one event. */
  @Output() readonly resumeAiOut = new EventEmitter<void>();

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

  /** Older-history paging (infinite scroll up). The page owns the
   *  fetch; the thread only reports "operator reached the top". */
  @Input() loadingOlder = false;
  @Input() hasOlder = false;
  @Output() readonly loadOlder = new EventEmitter<void>();

  @ViewChild('scrollHost') protected scrollHost?: ElementRef<HTMLDivElement>;

  /** Count of messages that arrived while the operator was scrolled up
   *  reading history. Drives the "↓ N new messages" pill; cleared when
   *  they return to the bottom. */
  protected readonly unseenCount = signal(0);
  /** Message id briefly highlighted after a quoted-reply jump. */
  protected readonly flashId = signal<string | null>(null);

  /** Pixels from the bottom that still count as "at the bottom". */
  private static readonly STICK_THRESHOLD_PX = 120;
  /** Pixels from the top that trigger loading the previous page. */
  private static readonly LOAD_OLDER_THRESHOLD_PX = 80;

  private lastConversationId: string | null = null;
  private forceScrollToBottom = true;
  private lastFirstId: string | null = null;
  private lastLastId: string | null = null;
  private lastCount = 0;
  /** scrollHeight captured before older messages are prepended, so the
   *  viewport can be shifted by exactly the added height. */
  private heightBeforePrepend: number | null = null;
  private flashTimer: ReturnType<typeof setTimeout> | null = null;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['conversation'] && this.conversation?.id !== this.lastConversationId) {
      this.lastConversationId = this.conversation?.id ?? null;
      this.forceScrollToBottom = true;
      this.unseenCount.set(0);
      this.pickerOpenFor.set(null);
      this.heightBeforePrepend = null;
      this.lastLastId = null;
    }
    if (changes['detail'] && this.scrollHost) {
      // Older page prepended (the previous first message is still in
      // the list but no longer first): remember the height so
      // ngAfterViewChecked keeps the operator's reading position steady.
      const msgs = this.detail?.messages ?? [];
      const firstId = msgs[0]?.id ?? null;
      if (
        firstId &&
        this.lastFirstId &&
        firstId !== this.lastFirstId &&
        msgs.some((m) => m.id === this.lastFirstId)
      ) {
        this.heightBeforePrepend = this.scrollHost.nativeElement.scrollHeight;
      }
    }
  }

  ngAfterViewChecked(): void {
    const el = this.scrollHost?.nativeElement;
    if (!el) return;
    const msgs = this.detail?.messages ?? [];
    const last = msgs[msgs.length - 1] ?? null;
    const lastId = last?.id ?? null;

    if (this.heightBeforePrepend !== null) {
      const delta = el.scrollHeight - this.heightBeforePrepend;
      this.heightBeforePrepend = null;
      if (delta > 0) el.scrollTop += delta;
    } else if (this.forceScrollToBottom && msgs.length > 0 && !this.loading) {
      this.forceScrollToBottom = false;
      requestAnimationFrame(() => (el.scrollTop = el.scrollHeight));
    } else if (last && lastId !== this.lastLastId && this.lastLastId !== null) {
      // New tail message. Follow it when the operator is already at the
      // bottom or sent it themselves; otherwise count it for the pill.
      const ownSend = last.direction === 'out' && (this.isPending(last) || last.is_internal);
      if (ownSend || this.isNearBottom(el)) {
        requestAnimationFrame(() => (el.scrollTop = el.scrollHeight));
      } else {
        this.unseenCount.update((n) => n + Math.max(1, msgs.length - this.lastCount));
      }
    }

    this.lastFirstId = msgs[0]?.id ?? null;
    this.lastLastId = lastId;
    this.lastCount = msgs.length;
  }

  protected onScroll(): void {
    const el = this.scrollHost?.nativeElement;
    if (!el) return;
    if (this.isNearBottom(el)) this.unseenCount.set(0);
    if (
      el.scrollTop < ChatThreadComponent.LOAD_OLDER_THRESHOLD_PX &&
      this.hasOlder &&
      !this.loadingOlder
    ) {
      this.loadOlder.emit();
    }
  }

  protected scrollToBottom(): void {
    const el = this.scrollHost?.nativeElement;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    this.unseenCount.set(0);
  }

  /** Quoted-reply click: scroll the original into view and flash it.
   *  Quotes of messages outside the loaded window stay inert. */
  protected jumpToMessage(id: string | null): void {
    if (!id) return;
    const target = this.scrollHost?.nativeElement.querySelector<HTMLElement>(
      `[data-message-id="${id}"]`,
    );
    if (!target) return;
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    this.flashId.set(id);
    if (this.flashTimer) clearTimeout(this.flashTimer);
    this.flashTimer = setTimeout(() => this.flashId.set(null), 1600);
  }

  private isNearBottom(el: HTMLElement): boolean {
    return (
      el.scrollHeight - el.scrollTop - el.clientHeight < ChatThreadComponent.STICK_THRESHOLD_PX
    );
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    this.pickerOpenFor.set(null);
  }

  /** Day-divider label ("Today" / "Yesterday" / "Mon, 14 Sep") shown
   *  above the first message of each calendar day. Null when the
   *  message is on the same day as its predecessor. */
  protected dayDividerFor(index: number): string | null {
    const msgs = this.detail?.messages ?? [];
    const m = msgs[index];
    if (!m) return null;
    const cur = new Date(m.sent_at || m.created_at);
    if (index > 0) {
      const prevMsg = msgs[index - 1];
      const prev = new Date(prevMsg.sent_at || prevMsg.created_at);
      if (prev.toDateString() === cur.toDateString()) return null;
    }
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    if (cur.toDateString() === today.toDateString()) return 'Today';
    if (cur.toDateString() === yesterday.toDateString()) return 'Yesterday';
    const sameYear = cur.getFullYear() === today.getFullYear();
    return cur.toLocaleDateString([], {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      ...(sameYear ? {} : { year: 'numeric' }),
    });
  }

  /** Bubble widths (%) for the loading skeleton. */
  protected readonly skeletonRows = [55, 40, 65, 35, 50];

  /** "Asha, Ravi" for a note's @-mentions; falls back to a count when
   *  a mentioned user is no longer in the staff directory. */
  protected mentionNames(m: ConversationMessage): string {
    const ids = m.mentioned_user_ids ?? [];
    const names = ids
      .map((id) => this.staffById.get(id)?.full_name)
      .filter((n): n is string => !!n);
    if (names.length === ids.length) return names.join(', ');
    return `${ids.length} ${ids.length === 1 ? 'person' : 'people'}`;
  }

  /** Bubble timestamp — time only; the day lives in the divider. */
  protected formatClock(iso: string | null): string {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
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
    if (this.isPending(m)) return 'pending';
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

  /** WhatsApp media attachments (image / video / audio / document /
   *  sticker) with their position in `attachments[]` — the media proxy
   *  addresses them by index. Step-6 reply attribution and email files
   *  (keyed on `storage_key`) share the array but are rendered elsewhere. */
  protected mediaAttachments(
    m: ConversationMessage,
  ): Array<{ att: MediaAttachment; index: number }> {
    const out: Array<{ att: MediaAttachment; index: number }> = [];
    (m.attachments ?? []).forEach((raw, index) => {
      const t = (raw as { type?: string }).type;
      if (t === 'image' || t === 'video' || t === 'audio' || t === 'document' || t === 'sticker') {
        out.push({ att: raw as unknown as MediaAttachment, index });
      }
    });
    return out;
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

  /** Bubble text as displayed to the operator. Email inbound bodies
   *  arrive with the full Gmail/Outlook reply quote chain appended
   *  ("On <date> <sender> wrote:" + ``>``-prefixed lines). That noise
   *  swamps the actual new reply, so on the email channel we strip the
   *  quote block and render only the fresh text. Non-email channels
   *  pass through unchanged. */
  protected visibleText(m: ConversationMessage): string {
    const raw = m.text ?? '';
    if (!raw || this.conversation?.channel !== 'email') return raw;
    return stripEmailQuote(raw);
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
    const text = this.visibleText(m);
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

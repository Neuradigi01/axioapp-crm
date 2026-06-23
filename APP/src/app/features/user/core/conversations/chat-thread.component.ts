import {
  AfterViewChecked,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  Output,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import {
  Conversation,
  ConversationDetail,
  ConversationMessage,
  ConversationTagRef,
  MessageReaction,
} from './conversations-api.service';
import { ReactionPickerComponent } from './reaction-picker.component';
import { SessionWindowBannerComponent } from './session-window-banner.component';
import { TagChipComponent } from './tag-chip.component';
import { TagManagerComponent } from './tag-manager.component';
import { StaffListItem } from '../staff/staff-api.service';
import {
  OwnerColor,
  ownerColor,
  staffInitials,
} from '../shared/owner-color.util';
import { FurnitureAuthService } from '../auth/auth.service';

/**
 * Chat thread — renders bubbles, auto-scrolls to bottom on new
 * messages. The conversation header shows the external_id + channel +
 * the AI-Handled / Needs-Human pill (clickable: emits `toggleAi`).
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
    SessionWindowBannerComponent,
    TagChipComponent,
    TagManagerComponent,
  ],
  templateUrl: './chat-thread.component.html',
})
export class ChatThreadComponent implements AfterViewChecked {
  private readonly auth = inject(FurnitureAuthService);

  @Input({ required: true }) conversation!: Conversation;
  @Input() detail: ConversationDetail | null = null;
  @Input() loading = false;
  @Input() staffById: Map<string, StaffListItem> = new Map();

  @Output() readonly toggleAi = new EventEmitter<boolean>();

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

  /** Step 15 — out-of-session "Pick template" CTA was clicked on the
   *  banner. Parent decides where to route (templates page today;
   *  future Step 16 might wire to in-thread template send). */
  @Output() readonly pickTemplate = new EventEmitter<void>();

  protected toggleTagManager(): void {
    this.tagManagerOpen.update((v) => !v);
  }

  protected closeTagManager(): void {
    this.tagManagerOpen.set(false);
  }

  protected onTagsChanged(tags: ConversationTagRef[]): void {
    this.tagsChanged.emit(tags);
  }

  /** Permission gate for the reassign click target — same key the
   * backend enforces on `PATCH /api/v1/conversations/{id}`. */
  protected readonly canReassign = computed(() =>
    this.auth.hasPermission('conversations.write'),
  );

  @ViewChild('scrollHost') protected scrollHost?: ElementRef<HTMLDivElement>;

  private lastMessageCount = 0;

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
    return new Date(iso).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
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
  protected tickState(
    m: ConversationMessage,
  ): 'read' | 'delivered' | 'sent' | 'pending' {
    if (m.read_at) return 'read';
    if (m.delivered_at) return 'delivered';
    if (m.sent_at) return 'sent';
    return 'pending';
  }

  protected toggle(): void {
    this.toggleAi.emit(!this.conversation.ai_handling);
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

  protected interactiveKind(
    m: ConversationMessage,
  ): 'reply_buttons' | 'cta_url' | 'list' | null {
    const p = m.interactive_payload;
    if (!p || typeof p !== 'object') return null;
    const k = (p as { kind?: string }).kind;
    return k === 'reply_buttons' || k === 'cta_url' || k === 'list'
      ? k
      : null;
  }

  protected interactiveButtons(
    m: ConversationMessage,
  ): Array<{ id: string; title: string }> {
    const p = m.interactive_payload as
      | { buttons?: Array<{ id?: string; title?: string }> }
      | null;
    if (!p?.buttons) return [];
    return p.buttons
      .filter((b) => typeof b.id === 'string' && typeof b.title === 'string')
      .map((b) => ({ id: b.id as string, title: b.title as string }));
  }

  protected interactiveCta(
    m: ConversationMessage,
  ): { button_text: string; url: string } | null {
    const p = m.interactive_payload as
      | { button_text?: string; url?: string }
      | null;
    if (!p?.button_text || !p?.url) return null;
    return { button_text: p.button_text, url: p.url };
  }

  protected interactiveListSections(
    m: ConversationMessage,
  ): Array<{
    title: string;
    rows: Array<{ id: string; title: string; description?: string }>;
  }> {
    const p = m.interactive_payload as
      | {
          sections?: Array<{
            title?: string;
            rows?: Array<{
              id?: string;
              title?: string;
              description?: string;
            }>;
          }>;
        }
      | null;
    if (!p?.sections) return [];
    return p.sections.map((s) => ({
      title: s.title ?? '',
      rows: (s.rows ?? [])
        .filter(
          (r) => typeof r.id === 'string' && typeof r.title === 'string',
        )
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
      return (
        t === 'image' ||
        t === 'video' ||
        t === 'audio' ||
        t === 'document'
      );
    }).length;
  }

  // --- Reply / quote / reactions (Step 7) ----------------------------

  /** Look up the message being quoted in the in-memory thread cache.
   *  Cross-pagination quotes fall back to null — the bubble renders
   *  "Original message" without the body preview. */
  protected quotedMessage(
    m: ConversationMessage,
  ): ConversationMessage | null {
    if (!m.reply_to_message_id || !this.detail) return null;
    return (
      this.detail.messages.find((x) => x.id === m.reply_to_message_id) ?? null
    );
  }

  /** Short preview for a quoted block — uses the original's text when
   *  available, else the first media attachment's type emoji ("📷
   *  Photo" / "🎥 Video" / etc.) per the spec's smoke point 7. */
  protected quotedPreview(target: ConversationMessage | null): string {
    if (!target) return 'Original message';
    if (target.text) return target.text;
    const att = (target.attachments ?? []).find((a) => {
      const t = (a as { type?: string }).type;
      return (
        t === 'image' || t === 'video' || t === 'audio' || t === 'document'
      );
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
  protected groupedReactions(
    m: ConversationMessage,
  ): Array<{ emoji: string; count: number }> {
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
    const mine = (m.reactions ?? []).find(
      (r: MessageReaction) => r.actor === me,
    );
    return mine?.emoji ?? null;
  }

  protected openPicker(messageId: string): void {
    this.pickerOpenFor.update((cur) =>
      cur === messageId ? null : messageId,
    );
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

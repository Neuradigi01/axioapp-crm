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
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import {
  Conversation,
  ConversationDetail,
  ConversationMessage,
} from './conversations-api.service';
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
  imports: [LucideAngularModule],
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
}

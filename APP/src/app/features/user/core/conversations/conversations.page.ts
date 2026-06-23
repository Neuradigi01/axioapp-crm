import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';

import {
  Conversation,
  ConversationDetail,
  ConversationListQuery,
  ConversationMessage,
  ConversationTagRef,
  ConversationsApiService,
} from './conversations-api.service';
import { ChatThreadComponent } from './chat-thread.component';
import {
  ComposeBarComponent,
  ComposerMediaPayload,
  ComposerNotePayload,
} from './compose-bar.component';
import { ConversationListComponent } from './conversation-list.component';
import {
  InteractiveBuilderComponent,
  InteractivePayload,
} from './interactive-builder.component';
import { NotificationsApiService } from '../notifications/notifications-api.service';
import { StaffApiService, StaffListItem } from '../staff/staff-api.service';
import {
  ReassignConfirm,
  ReassignModalComponent,
} from '../shared/reassign-modal/reassign-modal.component';
import { FurnitureAuthService } from '../auth/auth.service';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Conversations page â€” split inbox layout. Owns:
 *
 *   - the list of conversations + the filter signals
 *   - the currently-selected conversation id + its loaded detail
 *   - the WS hook that listens to notifications and refreshes the
 *     list / thread when an inbound `conversation.message` lands
 *
 * Children are dumb: list/thread/compose receive data via inputs and
 * emit events back up so the parent stays the single source of truth.
 *
 * The WS hook reuses the existing notifications stream (the master
 * prompt's DEFAULT decision) rather than opening a second socket.
 */
@Component({
  selector: 'app-conversations-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ConversationListComponent,
    ChatThreadComponent,
    ComposeBarComponent,
    InteractiveBuilderComponent,
    ReassignModalComponent,
  ],
  templateUrl: './conversations.page.html',
})
export class ConversationsPageComponent {
  private readonly api = inject(ConversationsApiService);
  private readonly notifications = inject(NotificationsApiService);
  private readonly staffApi = inject(StaffApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  /** Logged-in user id — drives the list component's "Mine" chip. */
  protected readonly currentUserId = this.auth.currentUserId;

  /** Wire value to hydrate the list's assignee chip with on first
   * render. Read from `sessionStorage` once; keyed by `org_id` so two
   * orgs the same user belongs to don't leak filters between sessions. */
  protected readonly initialAssignee = this.readPersistedAssignee();

  protected readonly items = signal<Conversation[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly selectedId = signal<string | null>(null);
  protected readonly detail = signal<ConversationDetail | null>(null);
  protected readonly threadLoading = signal(false);

  protected readonly filters = signal<ConversationListQuery>({});

  /** Staff list indexed by user id — resolves `assigned_to_id` and
   * `sender_user_id` to display names. Loaded once at page construct
   * via `GET /api/v1/staff`; the list is small (org-wide staff) and
   * rarely changes within a session. */
  protected readonly staffById = signal<Map<string, StaffListItem>>(new Map());

  /** Step 13 — flat staff array for the @-mention picker in the
   *  composer. Derived from `staffById` (single source of truth). */
  protected readonly staffList = computed<StaffListItem[]>(() =>
    Array.from(this.staffById().values()),
  );

  /** When `true`, the reassign modal is rendered inline and bound to
   * `selectedConversation()`. Cancel/confirm flip it back to `false`. */
  protected readonly reassignOpen = signal(false);
  protected readonly reassignSubmitting = signal(false);
  protected readonly reassignError = signal<string | null>(null);

  /** When `true`, the interactive-message builder modal is mounted.
   *  Lives outside the compose bar so dragging the dialog around
   *  doesn't blow away the composer's transient state (staged file,
   *  partially-typed caption, etc.). */
  protected readonly interactiveOpen = signal(false);

  /** Step 7: message currently being quoted by the composer. Null
   *  when not in reply mode. Cleared on send-success, Esc, or the X
   *  on the snippet. */
  protected readonly replyingTo = signal<ConversationMessage | null>(null);

  protected readonly selectedConversation = computed<Conversation | null>(() => {
    const id = this.selectedId();
    return this.items().find((c) => c.id === id) ?? null;
  });

  /** Last notification fingerprint we've already reacted to â€” guards
   * against re-running the refresh loop when the signal re-emits with
   * the same head element. */
  private lastSeenNotificationId: string | null = null;

  constructor() {
    // Seed the filter from the persisted assignee BEFORE the first
    // list call so the request goes out with the right `?assigned_to=…`.
    if (this.initialAssignee) {
      this.filters.set({ assigned_to: this.initialAssignee });
    }
    this.reloadList();
    this.loadStaff();

    // WS hook: react to the notifications signal. The notifications
    // service prepends new rows; we only care about `conversation.message`.
    effect(() => {
      const head = this.notifications.recent()[0];
      if (!head) return;
      if (head.id === this.lastSeenNotificationId) return;
      this.lastSeenNotificationId = head.id;
      if (head.type !== 'conversation.message') return;
      this.onIncomingNotification(head.payload);
    });
  }

  /** One-shot staff load at page mount. Failure is non-fatal — badges
   * fall back to "?" initials and the neutral grey palette. */
  private loadStaff(): void {
    this.staffApi
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          const map = new Map<string, StaffListItem>();
          for (const r of rows) map.set(r.id, r);
          this.staffById.set(map);
        },
        error: () => {
          // Intentionally silent — page remains usable; the badge
          // markup degrades gracefully when the map is empty.
        },
      });
  }

  protected onFiltersChange(next: ConversationListQuery): void {
    // Preserve assigned_to across channel/status/q updates.
    const assigned_to = this.filters().assigned_to;
    this.filters.set({ ...next, ...(assigned_to ? { assigned_to } : {}) });
    this.reloadList();
  }

  protected onAssigneeFilterChange(value: string | undefined): void {
    this.filters.update((prev) => {
      const { assigned_to: _omit, ...rest } = prev;
      return value ? { ...rest, assigned_to: value } : rest;
    });
    this.persistAssignee(value);
    this.reloadList();
  }

  // --- Session window (Step 15) --------------------------------------

  /** True when the selected conversation is on WhatsApp AND outside
   *  its 24-hour session window. Drives the composer's text-input
   *  disabled state. Non-WhatsApp conversations + missing state
   *  (still loading) are treated as "in session" so the composer
   *  doesn't lock down spuriously. */
  protected readonly isOutOfSession = computed(() => {
    const state = this.detail()?.whatsapp_session_state;
    if (!state) return false;
    return !state.in_session;
  });

  /** Step 15 — banner's [Pick template] CTA. Routes to the templates
   *  page where the operator can pick + submit a template. In a
   *  future step this could open an inline template-send picker. */
  protected onPickTemplate(): void {
    // Lazy import: keep the page bundle lean by routing imperatively
    // instead of declaring RouterLink in this page (already a big file).
    window.location.href = '/user/whatsapp/templates';
  }

  // --- Tags (Step 14) ------------------------------------------------

  protected readonly tagFilterIds = signal<string[]>([]);

  protected onTagFilterChange(ids: string[]): void {
    this.tagFilterIds.set(ids);
    this.filters.update((prev) => {
      const { tag_ids: _omit, ...rest } = prev;
      return ids.length > 0 ? { ...rest, tag_ids: ids } : rest;
    });
    this.reloadList();
  }

  /** Step 14 — tag-manager dispatched a change. Patch the row in
   *  both the list signal and the detail signal so chips refresh
   *  immediately without a follow-up fetch. */
  protected onTagsChanged(tags: ConversationTagRef[]): void {
    const id = this.selectedId();
    if (!id) return;
    this.items.update((rows) =>
      rows.map((r) => (r.id === id ? { ...r, tags } : r)),
    );
    this.detail.update((d) =>
      d
        ? {
            ...d,
            conversation: { ...d.conversation, tags },
          }
        : d,
    );
  }

  // --- sessionStorage helpers (org-prefixed) ------------------------------

  private storageKey(): string {
    const orgId = this.auth.currentOrg()?.id ?? 'anon';
    return `conversations:assignee:${orgId}`;
  }

  private readPersistedAssignee(): string {
    try {
      return sessionStorage.getItem(this.storageKey()) ?? '';
    } catch {
      // Private-mode browsers throw on sessionStorage access.
      return '';
    }
  }

  private persistAssignee(value: string | undefined): void {
    try {
      if (value) sessionStorage.setItem(this.storageKey(), value);
      else sessionStorage.removeItem(this.storageKey());
    } catch {
      // Best-effort; failure is silent.
    }
  }

  protected onSelect(id: string): void {
    this.selectedId.set(id);
    this.loadDetail(id);
  }

  protected onSendText(text: string): void {
    const id = this.selectedId();
    if (!id || !text.trim()) return;

    // Step 7: pull the in-flight reply target (set by chat-thread's
    // Reply click) and clear the composer's reply mode atomically.
    const replyTarget = this.replyingTo();
    this.replyingTo.set(null);

    // Optimistic append while the POST is in flight.
    const optimistic: ConversationMessage = {
      id: 'tmp-' + Math.random().toString(36).slice(2),
      org_id: '',
      conversation_id: id,
      direction: 'out',
      sender_user_id: null,
      text,
      attachments: [],
      interactive_payload: null,
      reply_to_message_id: replyTarget?.id ?? null,
      reactions: [],
      is_internal: false,
      mentioned_user_ids: [],
      channel_message_id: null,
      sent_at: new Date().toISOString(),
      delivered_at: null,
      read_at: null,
      created_at: new Date().toISOString(),
    };
    this.detail.update((d) =>
      d ? { ...d, messages: [...d.messages, optimistic] } : d,
    );

    this.api
      .send(id, text, replyTarget?.id ?? null)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (real) => {
          this.detail.update((d) =>
            d
              ? {
                  ...d,
                  messages: d.messages.map((m) =>
                    m.id === optimistic.id ? real : m,
                  ),
                }
              : d,
          );
          this.bumpListLastMessage(id, real.sent_at ?? real.created_at);
        },
        error: (err: HttpErrorResponse) => {
          // Roll the optimistic row back; show the error inline on the
          // thread so the user notices.
          this.detail.update((d) =>
            d
              ? {
                  ...d,
                  messages: d.messages.filter((m) => m.id !== optimistic.id),
                }
              : d,
          );
          this.loadError.set(
            extractApiError(err) ?? 'Could not send message.',
          );
        },
      });
  }

  // --- Internal note (Step 13) ---------------------------------------

  protected onSendNote(payload: ComposerNotePayload): void {
    const id = this.selectedId();
    if (!id || !payload.text.trim()) return;

    const optimistic: ConversationMessage = {
      id: 'tmp-' + Math.random().toString(36).slice(2),
      org_id: '',
      conversation_id: id,
      direction: 'out',
      sender_user_id: this.auth.currentUserId(),
      text: payload.text,
      attachments: [],
      interactive_payload: null,
      reply_to_message_id: null,
      reactions: [],
      is_internal: true,
      mentioned_user_ids: payload.mentions,
      channel_message_id: null,
      sent_at: new Date().toISOString(),
      delivered_at: null,
      read_at: null,
      created_at: new Date().toISOString(),
    };
    this.detail.update((d) =>
      d ? { ...d, messages: [...d.messages, optimistic] } : d,
    );

    this.api
      .postNote(id, payload.text, payload.mentions)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (real) => {
          this.detail.update((d) =>
            d
              ? {
                  ...d,
                  messages: d.messages.map((m) =>
                    m.id === optimistic.id ? real : m,
                  ),
                }
              : d,
          );
          this.bumpListLastMessage(id, real.sent_at ?? real.created_at);
        },
        error: (err: HttpErrorResponse) => {
          this.detail.update((d) =>
            d
              ? {
                  ...d,
                  messages: d.messages.filter(
                    (m) => m.id !== optimistic.id,
                  ),
                }
              : d,
          );
          this.loadError.set(
            extractApiError(err) ?? 'Could not post the note.',
          );
        },
      });
  }

  // --- Reply / React (Step 7) ----------------------------------------

  protected onReplyTo(m: ConversationMessage): void {
    this.replyingTo.set(m);
  }

  protected onClearReply(): void {
    this.replyingTo.set(null);
  }

  protected onReact(evt: { messageId: string; emoji: string | null }): void {
    const conversationId = this.selectedId();
    if (!conversationId) return;
    this.api
      .reactToMessage(conversationId, evt.messageId, evt.emoji)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.detail.update((d) =>
            d
              ? {
                  ...d,
                  messages: d.messages.map((m) =>
                    m.id === updated.id ? updated : m,
                  ),
                }
              : d,
          );
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(
            extractApiError(err) ?? 'Could not update reaction.',
          );
        },
      });
  }

  // --- Interactive (Step 6) ----------------------------------------------

  protected openInteractive(): void {
    if (!this.selectedConversation()) return;
    this.interactiveOpen.set(true);
  }

  protected closeInteractive(): void {
    this.interactiveOpen.set(false);
  }

  /**
   * Outbound interactive message — reply buttons / CTA URL / list
   * (whatsapp-platform-upgrade Step 6). The builder modal emits the
   * validated payload; we close the modal, optimistic-append the
   * placeholder bubble, then swap in the server's row.
   */
  protected onSendInteractive(payload: InteractivePayload): void {
    const id = this.selectedId();
    if (!id) return;
    this.interactiveOpen.set(false);

    const previewText = payload.body || '[interactive message]';
    const optimistic: ConversationMessage = {
      id: 'tmp-' + Math.random().toString(36).slice(2),
      org_id: '',
      conversation_id: id,
      direction: 'out',
      sender_user_id: null,
      text: previewText,
      attachments: [],
      interactive_payload: payload as unknown as Record<string, unknown>,
      reply_to_message_id: null,
      reactions: [],
      is_internal: false,
      mentioned_user_ids: [],
      channel_message_id: null,
      sent_at: new Date().toISOString(),
      delivered_at: null,
      read_at: null,
      created_at: new Date().toISOString(),
    };
    this.detail.update((d) =>
      d ? { ...d, messages: [...d.messages, optimistic] } : d,
    );

    this.api
      .sendInteractive(id, payload as unknown as Record<string, unknown>)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (real) => {
          this.detail.update((d) =>
            d
              ? {
                  ...d,
                  messages: d.messages.map((m) =>
                    m.id === optimistic.id ? real : m,
                  ),
                }
              : d,
          );
          this.bumpListLastMessage(id, real.sent_at ?? real.created_at);
        },
        error: (err: HttpErrorResponse) => {
          this.detail.update((d) =>
            d
              ? {
                  ...d,
                  messages: d.messages.filter(
                    (m) => m.id !== optimistic.id,
                  ),
                }
              : d,
          );
          this.loadError.set(
            extractApiError(err) ?? 'Could not send interactive message.',
          );
        },
      });
  }

  /**
   * Outbound media message for WhatsApp conversations (whatsapp-
   * platform-upgrade Step 5). Optimistic-append the placeholder, fire
   * the multipart upload, then swap in the server's row. On failure
   * the placeholder is rolled back and the friendly error from the
   * backend (oversize / bad MIME / Meta refusal) lands in `loadError`.
   */
  protected onSendMedia(payload: ComposerMediaPayload): void {
    const id = this.selectedId();
    if (!id) return;

    const placeholderText = payload.caption ?? `[${payload.type}]`;
    const optimistic: ConversationMessage = {
      id: 'tmp-' + Math.random().toString(36).slice(2),
      org_id: '',
      conversation_id: id,
      direction: 'out',
      sender_user_id: null,
      text: placeholderText,
      attachments: [
        {
          type: payload.type,
          filename: payload.file.name,
          mime_type: payload.file.type,
          size_bytes: payload.file.size,
          caption: payload.caption ?? null,
          // No media_id yet — backend mints it.
          uploading: true,
        },
      ],
      interactive_payload: null,
      reply_to_message_id: null,
      reactions: [],
      is_internal: false,
      mentioned_user_ids: [],
      channel_message_id: null,
      sent_at: new Date().toISOString(),
      delivered_at: null,
      read_at: null,
      created_at: new Date().toISOString(),
    };
    this.detail.update((d) =>
      d ? { ...d, messages: [...d.messages, optimistic] } : d,
    );

    this.api
      .sendMedia(id, payload.file, payload.type, payload.caption)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (real) => {
          this.detail.update((d) =>
            d
              ? {
                  ...d,
                  messages: d.messages.map((m) =>
                    m.id === optimistic.id ? real : m,
                  ),
                }
              : d,
          );
          this.bumpListLastMessage(id, real.sent_at ?? real.created_at);
        },
        error: (err: HttpErrorResponse) => {
          this.detail.update((d) =>
            d
              ? {
                  ...d,
                  messages: d.messages.filter(
                    (m) => m.id !== optimistic.id,
                  ),
                }
              : d,
          );
          this.loadError.set(
            extractApiError(err) ?? 'Could not send media.',
          );
        },
      });
  }

  // --- Reassign (assignee pill on the thread header) ----------------------

  protected openReassign(): void {
    if (!this.selectedConversation()) return;
    this.reassignError.set(null);
    this.reassignSubmitting.set(false);
    this.reassignOpen.set(true);
  }

  protected closeReassign(): void {
    this.reassignOpen.set(false);
    this.reassignSubmitting.set(false);
    this.reassignError.set(null);
  }

  protected onReassignConfirm(payload: ReassignConfirm): void {
    const conv = this.selectedConversation();
    if (!conv) return;
    this.reassignSubmitting.set(true);
    this.reassignError.set(null);
    this.api
      .patch(conv.id, { assigned_to_id: payload.userId })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          // Authoritative write-back — overrides any stale WS-driven
          // refresh that arrived during the PATCH round-trip.
          this.items.update((rows) =>
            rows.map((r) => (r.id === updated.id ? updated : r)),
          );
          this.detail.update((d) =>
            d ? { ...d, conversation: updated } : d,
          );
          this.closeReassign();
        },
        error: (err: HttpErrorResponse) => {
          this.reassignSubmitting.set(false);
          this.reassignError.set(
            extractApiError(err) ?? 'Could not update assignee.',
          );
        },
      });
  }

  protected onToggleAi(value: boolean): void {
    const id = this.selectedId();
    if (!id) return;
    this.api
      .patch(id, { ai_handling: value })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.items.update((rows) =>
            rows.map((r) => (r.id === updated.id ? updated : r)),
          );
          this.detail.update((d) =>
            d ? { ...d, conversation: updated } : d,
          );
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(
            extractApiError(err) ?? 'Could not update AI handling.',
          );
        },
      });
  }

  protected reloadList(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({ ...this.filters(), size: 100 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load conversations.',
          );
        },
      });
  }

  private loadDetail(id: string): void {
    this.threadLoading.set(true);
    this.api
      .detail(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (d) => {
          this.detail.set(d);
          this.threadLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.detail.set(null);
          this.threadLoading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load thread.',
          );
        },
      });
  }

  private onIncomingNotification(payload: Record<string, unknown>): void {
    const incomingId =
      typeof payload?.['conversation_id'] === 'string'
        ? (payload['conversation_id'] as string)
        : null;
    // Refresh the list so order + unread counts reflect the new state.
    this.reloadList();
    // Reload the thread only if the conversation in question is open.
    if (incomingId && incomingId === this.selectedId()) {
      this.loadDetail(incomingId);
    }
  }

  private bumpListLastMessage(id: string, isoTs: string): void {
    this.items.update((rows) =>
      rows
        .map((r) =>
          r.id === id ? { ...r, last_message_at: isoTs } : r,
        )
        .sort((a, b) => {
          const av = a.last_message_at ?? '';
          const bv = b.last_message_at ?? '';
          return bv.localeCompare(av);
        }),
    );
  }

}

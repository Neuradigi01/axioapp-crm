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
  ConversationsApiService,
} from './conversations-api.service';
import { ChatThreadComponent } from './chat-thread.component';
import { ComposeBarComponent } from './compose-bar.component';
import { ConversationListComponent } from './conversation-list.component';
import { NotificationsApiService } from '../notifications/notifications-api.service';
import { StaffApiService, StaffListItem } from '../staff/staff-api.service';
import {
  ReassignConfirm,
  ReassignModalComponent,
} from '../shared/reassign-modal/reassign-modal.component';
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
    ReassignModalComponent,
  ],
  templateUrl: './conversations.page.html',
})
export class ConversationsPageComponent {
  private readonly api = inject(ConversationsApiService);
  private readonly notifications = inject(NotificationsApiService);
  private readonly staffApi = inject(StaffApiService);
  private readonly destroyRef = inject(DestroyRef);

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

  /** When `true`, the reassign modal is rendered inline and bound to
   * `selectedConversation()`. Cancel/confirm flip it back to `false`. */
  protected readonly reassignOpen = signal(false);
  protected readonly reassignSubmitting = signal(false);
  protected readonly reassignError = signal<string | null>(null);

  protected readonly selectedConversation = computed<Conversation | null>(() => {
    const id = this.selectedId();
    return this.items().find((c) => c.id === id) ?? null;
  });

  /** Last notification fingerprint we've already reacted to â€” guards
   * against re-running the refresh loop when the signal re-emits with
   * the same head element. */
  private lastSeenNotificationId: string | null = null;

  constructor() {
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
    this.filters.set(next);
    this.reloadList();
  }

  protected onSelect(id: string): void {
    this.selectedId.set(id);
    this.loadDetail(id);
  }

  protected onSendText(text: string): void {
    const id = this.selectedId();
    if (!id || !text.trim()) return;

    // Optimistic append while the POST is in flight.
    const optimistic: ConversationMessage = {
      id: 'tmp-' + Math.random().toString(36).slice(2),
      org_id: '',
      conversation_id: id,
      direction: 'out',
      sender_user_id: null,
      text,
      attachments: [],
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
      .send(id, text)
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

import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ViewChild,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { MatSnackBar } from '@angular/material/snack-bar';
import { LucideAngularModule } from 'lucide-angular';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { ContactsApiService } from '../contacts/contacts-api.service';
import { MobileSelectComponent } from '../shared/forms/mobile-select.component';

import {
  Conversation,
  ConversationDetail,
  ConversationListQuery,
  ConversationMessage,
  ConversationStatus,
  ConversationTagRef,
  ConversationsApiService,
} from './conversations-api.service';
import { ChatThreadComponent } from './chat-thread.component';
import {
  ComposeBarComponent,
  ComposerLocationPayload,
  ComposerMediaPayload,
  ComposerNotePayload,
} from './compose-bar.component';
import { ConversationListComponent } from './conversation-list.component';
import { InteractiveBuilderComponent, InteractivePayload } from './interactive-builder.component';
import { NewConversationModalComponent } from './new-conversation-modal.component';
import { WhatsAppTemplatePickerComponent } from './whatsapp-template-picker.component';
import { NotificationsApiService } from '../notifications/notifications-api.service';
import { StaffApiService, StaffListItem } from '../staff/staff-api.service';
import {
  ReassignConfirm,
  ReassignModalComponent,
} from '../shared/reassign-modal/reassign-modal.component';
import { FurnitureAuthService } from '../auth/auth.service';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Conversations page — split inbox layout. Owns:
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
    NewConversationModalComponent,
    ReassignModalComponent,
    LucideAngularModule,
    MobileSelectComponent,
    WhatsAppTemplatePickerComponent,
  ],
  templateUrl: './conversations.page.html',
  host: { class: 'flex min-h-0 flex-1 flex-col' },
})
export class ConversationsPageComponent {
  private readonly api = inject(ConversationsApiService);
  private readonly notifications = inject(NotificationsApiService);
  private readonly staffApi = inject(StaffApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly snackBar = inject(MatSnackBar);

  /** Step 27b — handle to the compose-bar so we can read its
   *  current Send-From selection on send. The picker self-hides
   *  for single-number orgs; the ViewChild stays defined either
   *  way (the compose-bar instance always exists when a
   *  conversation is open). */
  @ViewChild('composeBar') protected composeBar?: ComposeBarComponent;

  /** Logged-in user id — drives the list component's "Mine" chip. */
  protected readonly currentUserId = this.auth.currentUserId;

  /** Wire value to hydrate the list's assignee chip with on first
   * render. Read from `sessionStorage` once; keyed by `org_id` so two
   * orgs the same user belongs to don't leak filters between sessions. */
  protected readonly initialAssignee = this.readPersistedAssignee();

  protected readonly items = signal<Conversation[]>([]);
  protected readonly loading = signal(false);
  /** Errors from the list / thread load paths. Rendered by the header
   *  banner. Cleared on next reload. */
  protected readonly loadError = signal<string | null>(null);
  /** Errors from send / patch / react actions. Rendered by the same
   *  banner but labelled per-action so a "Could not update reaction"
   *  toast doesn't read like a list-load failure. */
  protected readonly sendError = signal<string | null>(null);

  protected readonly selectedId = signal<string | null>(null);
  protected readonly detail = signal<ConversationDetail | null>(null);
  protected readonly threadLoading = signal(false);

  protected readonly filters = signal<ConversationListQuery>({});

  /** Status filter — lives in the page header (next to Refresh) so the
   * list panel keeps its full height for messages. Default is "all
   * statuses" so first-load matches previous behaviour. */
  protected readonly statusFilter = signal<ConversationStatus | ''>('');
  protected readonly statusOptions: Array<{ value: ConversationStatus | ''; label: string }> = [
    { value: '', label: 'All statuses' },
    { value: 'open', label: 'Open' },
    { value: 'snoozed', label: 'Snoozed' },
    { value: 'closed', label: 'Closed' },
  ];

  /** Staff list indexed by user id — resolves `assigned_to_id` and
   * `sender_user_id` to display names. Loaded once at page construct
   * via `GET /api/v1/staff`; the list is small (org-wide staff) and
   * rarely changes within a session. */
  protected readonly staffById = signal<Map<string, StaffListItem>>(new Map());

  /** Contact-name lookup for the list rows — resolves each row's
   *  `contact_id` to a display name so the list shows "Ananya Rao"
   *  instead of the raw phone/email `external_id`. Hydrated lazily
   *  after each `reloadList()`; already-fetched ids are skipped. */
  protected readonly contactsById = signal<Record<string, { id: string; full_name: string }>>({});

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

  /** When `true`, the new-conversation modal is mounted. The header
   *  `+ New` button opens it; the modal emits `started` (route to the
   *  fresh thread) or `cancel` (dismiss). */
  protected readonly newConversationOpen = signal(false);

  protected openNewConversation(): void {
    this.newConversationOpen.set(true);
  }

  protected closeNewConversation(): void {
    this.newConversationOpen.set(false);
  }

  /** Modal picked a contact and the server returned the conversation
   *  (either freshly created or the existing one if a thread was
   *  already open). Drop it into the list optimistically so the row
   *  appears without waiting for the next `reloadList()`, then open it. */
  protected onConversationStarted(conv: Conversation): void {
    this.newConversationOpen.set(false);
    this.items.update((rows) => {
      const withoutDup = rows.filter((r) => r.id !== conv.id);
      return [conv, ...withoutDup];
    });
    this.hydrateContacts([conv]);
    this.onSelect(conv.id);
  }

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

  /** Last notification fingerprint we've already reacted to — guards
   * against re-running the refresh loop when the signal re-emits with
   * the same head element. */
  private lastSeenNotificationId: string | null = null;

  /** Coalesce bursty WS notifications (10 inbound msgs in one second)
   *  into a single list-reload + at-most-one thread-refresh per window.
   *  Without this every notification fires a full `GET /conversations`
   *  plus a `hydrateContacts` forkJoin. */
  private static readonly RELOAD_DEBOUNCE_MS = 300;
  private pendingListReloadTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingDetailReload: {
    id: string;
    timer: ReturnType<typeof setTimeout>;
  } | null = null;

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

    // Clear any coalescing timers so we don't run a reload after the
    // component has been torn down (would leak subscriptions).
    this.destroyRef.onDestroy(() => {
      if (this.pendingListReloadTimer !== null) {
        clearTimeout(this.pendingListReloadTimer);
        this.pendingListReloadTimer = null;
      }
      if (this.pendingDetailReload !== null) {
        clearTimeout(this.pendingDetailReload.timer);
        this.pendingDetailReload = null;
      }
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
    // Preserve assigned_to + status across channel/q updates — the list
    // child owns channel + search, the page header owns status, so
    // neither should clobber the other.
    const { assigned_to, status } = this.filters();
    this.filters.set({
      ...next,
      ...(assigned_to ? { assigned_to } : {}),
      ...(status ? { status } : {}),
    });
    this.reloadList();
  }

  /** Page-header status filter — patches the list query and reloads.
   *  Accepts the picked value directly (from `crm-mobile-select`'s
   *  `valueChange`) so no synthetic Event parsing is needed. */
  protected onStatusFilterChange(value: string): void {
    const cast = value as ConversationStatus | '';
    this.statusFilter.set(cast);
    this.filters.update((prev) => {
      const { status: _omit, ...rest } = prev;
      return cast ? { ...rest, status: cast } : rest;
    });
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
   *  doesn't lock down spuriously. Extra channel guard so a stale
   *  ``detail()`` (left over during a WhatsApp → Email switch) never
   *  leaks the WhatsApp expired-window state onto an email thread. */
  protected readonly isOutOfSession = computed(() => {
    const conv = this.selectedConversation();
    if (!conv || conv.channel !== 'whatsapp') return false;
    const state = this.detail()?.whatsapp_session_state;
    if (!state) return false;
    return !state.in_session;
  });

  /** Compose-bar's inline WhatsApp template picker just sent a
   *  template. Optimistic-append the message + bump the list row so
   *  the thread reflects the send without waiting for a poll. */
  protected onTemplateSent(msg: ConversationMessage): void {
    this.detail.update((d) =>
      d && d.conversation.id === msg.conversation_id ? { ...d, messages: [...d.messages, msg] } : d,
    );
    this.bumpListLastMessage(msg.conversation_id, msg.sent_at ?? msg.created_at);
  }

  /** Inline picker surfaced an error (network / Meta refusal / etc).
   *  Route through the same send-error banner every other write path
   *  uses so the operator sees the reason above the thread. */
  protected onTemplateError(message: string): void {
    this.sendError.set(message);
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
    this.items.update((rows) => rows.map((r) => (r.id === id ? { ...r, tags } : r)));
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

  /** Mobile back button — clears the selection so the list pane
   *  re-appears full-width on <md screens. Desktop keeps both panes
   *  visible so the button is hidden there. */
  protected deselect(): void {
    this.selectedId.set(null);
    this.replyingTo.set(null);
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
      is_ai: false,
      channel_message_id: null,
      sent_at: new Date().toISOString(),
      delivered_at: null,
      read_at: null,
      created_at: new Date().toISOString(),
    };
    this.detail.update((d) => (d ? { ...d, messages: [...d.messages, optimistic] } : d));

    // Step 27b — pull the operator's Send-From selection (null
    // when single-number org / picker hidden) so the backend
    // resolves the adapter against the chosen phone.
    const sendFromPhoneId = this.composeBar?.currentSendFromPhoneId() ?? null;

    // Route by channel: email goes to the typed email-reply endpoint
    // (subject + connected-mailbox account); everything else uses the
    // generic /messages send. The email path ignores reply-target /
    // send-from-phone — those are WhatsApp / SMS concerns.
    const conv = this.selectedConversation();
    const sendCall =
      conv?.channel === 'email'
        ? this.api.sendEmailReply(id, { bodyText: text })
        : this.api.send(id, text, replyTarget?.id ?? null, sendFromPhoneId);

    sendCall.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (real) => {
        this.swapOptimisticMessage(id, optimistic.id, real);
        this.bumpListLastMessage(id, real.sent_at ?? real.created_at);
      },
      error: (err: HttpErrorResponse) => {
        this.removeOptimisticMessage(id, optimistic.id);
        // Channel-specific fallback copy so an email failure doesn't
        // read as a WhatsApp one. Backend detail (extractApiError)
        // takes precedence when present.
        const fallback =
          conv?.channel === 'email'
            ? 'Could not send this email. Check your connected mailbox and try again.'
            : 'Could not send this message. Try again in a moment.';
        this.sendError.set(extractApiError(err) ?? fallback);
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
      is_ai: false,
      channel_message_id: null,
      sent_at: new Date().toISOString(),
      delivered_at: null,
      read_at: null,
      created_at: new Date().toISOString(),
    };
    this.detail.update((d) => (d ? { ...d, messages: [...d.messages, optimistic] } : d));

    this.api
      .postNote(id, payload.text, payload.mentions)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (real) => {
          this.swapOptimisticMessage(id, optimistic.id, real);
          this.bumpListLastMessage(id, real.sent_at ?? real.created_at);
        },
        error: (err: HttpErrorResponse) => {
          this.removeOptimisticMessage(id, optimistic.id);
          this.sendError.set(extractApiError(err) ?? 'Could not post the note.');
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
          this.mutateDetailForConversation(conversationId, (d) => ({
            ...d,
            messages: d.messages.map((m) => (m.id === updated.id ? updated : m)),
          }));
        },
        error: (err: HttpErrorResponse) => {
          this.sendError.set(extractApiError(err) ?? 'Could not update reaction.');
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
      is_ai: false,
      channel_message_id: null,
      sent_at: new Date().toISOString(),
      delivered_at: null,
      read_at: null,
      created_at: new Date().toISOString(),
    };
    this.detail.update((d) => (d ? { ...d, messages: [...d.messages, optimistic] } : d));

    this.api
      .sendInteractive(id, payload as unknown as Record<string, unknown>)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (real) => {
          this.swapOptimisticMessage(id, optimistic.id, real);
          this.bumpListLastMessage(id, real.sent_at ?? real.created_at);
        },
        error: (err: HttpErrorResponse) => {
          this.removeOptimisticMessage(id, optimistic.id);
          this.sendError.set(extractApiError(err) ?? 'Could not send interactive message.');
        },
      });
  }

  /**
   * Outbound location share (Step 28). Posts via the standard
   * `/messages` endpoint with a `location` attachment — the
   * adapter detects it and ships the Meta-shape location envelope.
   * Optimistic-append a placeholder message so the inbox refresh
   * doesn't visually stutter while the POST is in flight.
   */
  protected onSendLocation(payload: ComposerLocationPayload): void {
    const id = this.selectedId();
    if (!id) return;
    const previewLabel = payload.name?.trim() || payload.address?.trim() || 'Shared location';
    const sendFromPhoneId = this.composeBar?.currentSendFromPhoneId() ?? null;
    const optimistic: ConversationMessage = {
      id: 'tmp-' + Math.random().toString(36).slice(2),
      org_id: '',
      conversation_id: id,
      direction: 'out',
      sender_user_id: null,
      text: `📍 ${previewLabel}`,
      attachments: [
        {
          type: 'location',
          latitude: payload.latitude,
          longitude: payload.longitude,
          name: payload.name ?? null,
          address: payload.address ?? null,
        },
      ],
      interactive_payload: null,
      reply_to_message_id: null,
      reactions: [],
      is_internal: false,
      mentioned_user_ids: [],
      is_ai: false,
      channel_message_id: null,
      sent_at: new Date().toISOString(),
      delivered_at: null,
      read_at: null,
      created_at: new Date().toISOString(),
    };
    this.detail.update((d) => (d ? { ...d, messages: [...d.messages, optimistic] } : d));
    this.api
      .send(id, `📍 ${previewLabel}`, null, sendFromPhoneId, [
        {
          type: 'location',
          latitude: payload.latitude,
          longitude: payload.longitude,
          name: payload.name,
          address: payload.address,
        },
      ])
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (msg) => {
          this.swapOptimisticMessage(id, optimistic.id, msg);
          this.bumpListLastMessage(id, msg.sent_at ?? msg.created_at);
        },
        error: (err: HttpErrorResponse) => {
          this.removeOptimisticMessage(id, optimistic.id);
          this.sendError.set(extractApiError(err) ?? 'Could not share location.');
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
      is_ai: false,
      channel_message_id: null,
      sent_at: new Date().toISOString(),
      delivered_at: null,
      read_at: null,
      created_at: new Date().toISOString(),
    };
    this.detail.update((d) => (d ? { ...d, messages: [...d.messages, optimistic] } : d));

    this.api
      .sendMedia(id, payload.file, payload.type, payload.caption)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (real) => {
          this.swapOptimisticMessage(id, optimistic.id, real);
          this.bumpListLastMessage(id, real.sent_at ?? real.created_at);
        },
        error: (err: HttpErrorResponse) => {
          this.removeOptimisticMessage(id, optimistic.id);
          this.sendError.set(extractApiError(err) ?? 'Could not send media.');
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
          this.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.detail.update((d) => (d ? { ...d, conversation: updated } : d));
          this.closeReassign();
        },
        error: (err: HttpErrorResponse) => {
          this.reassignSubmitting.set(false);
          this.reassignError.set(extractApiError(err) ?? 'Could not update assignee.');
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
          this.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.detail.update((d) => (d ? { ...d, conversation: updated } : d));
        },
        error: (err: HttpErrorResponse) => {
          this.sendError.set(extractApiError(err) ?? 'Could not update AI handling.');
        },
      });
  }

  // --- AI takeover (omnichannel Step 4) ------------------------------

  protected onTakeoverAi(): void {
    const id = this.selectedId();
    if (!id) return;
    this.api
      .pauseAi(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.detail.update((d) => (d ? { ...d, conversation: updated } : d));
          this._showToast('You took over from AI. Reload the thread to see the system message.');
          // Reload the thread so the freshly-inserted system marker
          // ("— {you} took over from AI —") lands in the UI without
          // needing a full page refresh.
          this._reloadDetail(id);
        },
        error: (err: HttpErrorResponse) => {
          if (err.status === 409) {
            const detail = err.error?.detail;
            const holder =
              (detail && typeof detail === 'object' && detail.holder_name) || 'Another user';
            this._showToast(`${holder} just took this over.`);
            // Refresh so our local state matches the winner's.
            this._reloadDetail(id);
          } else {
            this._showToast(extractApiError(err) ?? 'Could not take over.');
          }
        },
      });
  }

  protected onResumeAi(): void {
    const id = this.selectedId();
    if (!id) return;
    if (!window.confirm('Return this conversation to AI? The AI will handle future messages.')) {
      return;
    }
    this.api
      .resumeAi(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.detail.update((d) => (d ? { ...d, conversation: updated } : d));
          this._showToast('Returned to AI.');
          this._reloadDetail(id);
        },
        error: (err: HttpErrorResponse) => {
          const detail = err.error?.detail;
          if (err.status === 403 && detail?.reason === 'not_holder') {
            this._showToast('Only the person who took over (or an admin) can return this to AI.');
          } else {
            this._showToast(extractApiError(err) ?? 'Could not return to AI.');
          }
        },
      });
  }

  private _reloadDetail(id: string): void {
    this.api
      .detail(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (fresh) => this.detail.set(fresh),
        error: () => {
          /* silent — the takeover succeeded; the thread just won't
             re-render the system message until manual refresh. */
        },
      });
  }

  private _showToast(message: string): void {
    this.snackBar.open(message, 'OK', {
      duration: 3000,
      horizontalPosition: 'right',
      verticalPosition: 'top',
    });
  }

  /**
   * J.16 fix — header status pill emitted a new choice. PATCH,
   * update both the list-row and thread detail on success so the
   * status filter chip counts + the header pill re-render in one
   * pass without a full list reload.
   */
  protected onStatusChange(next: ConversationStatus): void {
    const id = this.selectedId();
    if (!id) return;
    this.api
      .patch(id, { status: next })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.detail.update((d) => (d ? { ...d, conversation: updated } : d));
        },
        error: (err: HttpErrorResponse) => {
          this.sendError.set(extractApiError(err) ?? 'Could not update conversation status.');
        },
      });
  }

  protected dismissSendError(): void {
    this.sendError.set(null);
  }

  protected reloadList(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.sendError.set(null);
    this.api
      .list({ ...this.filters(), size: 100 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.loading.set(false);
          this.hydrateContacts(resp.items);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load conversations.');
        },
      });
  }

  /** Fetch contact rows for any `contact_id` we haven't seen yet, so
   *  the list can show the person's name instead of the raw
   *  `external_id`. Individual failures are swallowed — a missing
   *  contact just falls back to the external id in the template. */
  private hydrateContacts(rows: Conversation[]): void {
    const ids = new Set<string>();
    for (const r of rows) {
      if (r.contact_id) ids.add(r.contact_id);
    }
    const cache = this.contactsById();
    const missing = [...ids].filter((id) => !cache[id]);
    if (missing.length === 0) return;
    forkJoin(missing.map((id) => this.contactsApi.get(id).pipe(catchError(() => of(null)))))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((results) => {
        this.contactsById.update((current) => {
          const next = { ...current };
          for (const c of results) {
            if (c) next[c.id] = { id: c.id, full_name: c.full_name };
          }
          return next;
        });
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
          // If the row we just opened has an unread badge, clear it
          // server-side. The endpoint is idempotent so we don't need
          // to gate on the count locally — the backend no-ops when
          // it's already 0. Best-effort: notification-refresh will
          // pick up the fresh count for the list badge.
          if ((d.conversation.unread_count ?? 0) > 0) {
            this.api
              .markRead(id)
              .pipe(takeUntilDestroyed(this.destroyRef))
              .subscribe({
                next: () => this.reloadList(),
                // Silent failure — the badge stays lit until next open
                // or reload. Not worth surfacing to the operator.
                error: () => undefined,
              });
          }
        },
        error: (err: HttpErrorResponse) => {
          this.detail.set(null);
          this.threadLoading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load thread.');
        },
      });
  }

  private onIncomingNotification(payload: Record<string, unknown>): void {
    const incomingId =
      typeof payload?.['conversation_id'] === 'string'
        ? (payload['conversation_id'] as string)
        : null;

    // Coalesce list-reload calls: a burst of N inbound messages fires
    // one reload after the debounce window rather than N sequential
    // `GET /conversations?size=100` + hydrateContacts fan-outs.
    if (this.pendingListReloadTimer === null) {
      this.pendingListReloadTimer = setTimeout(() => {
        this.pendingListReloadTimer = null;
        this.reloadList();
      }, ConversationsPageComponent.RELOAD_DEBOUNCE_MS);
    }

    // Same treatment for the thread refresh — only fire when the
    // incoming notification is for the currently-open conversation, and
    // coalesce successive events for the same id.
    if (incomingId && incomingId === this.selectedId()) {
      if (this.pendingDetailReload !== null) {
        clearTimeout(this.pendingDetailReload.timer);
      }
      const id = incomingId;
      const timer = setTimeout(() => {
        this.pendingDetailReload = null;
        // Guard against a thread switch during the debounce window.
        if (this.selectedId() === id) this.loadDetail(id);
      }, ConversationsPageComponent.RELOAD_DEBOUNCE_MS);
      this.pendingDetailReload = { id, timer };
    }
  }

  /** Splice an optimistic bubble into the current thread ONLY when the
   *  user hasn't switched conversations since the send was fired. Every
   *  optimistic-send + rollback path routes through this helper so the
   *  guard is applied uniformly. */
  private mutateDetailForConversation(
    conversationId: string,
    mutator: (d: ConversationDetail) => ConversationDetail,
  ): void {
    this.detail.update((d) => {
      if (!d) return d;
      if (d.conversation.id !== conversationId) return d;
      return mutator(d);
    });
  }

  /** Replace an optimistic (`tmp-…`) row with the server row. Skips the
   *  swap when the server row already appears in the thread (WS refresh
   *  race) so we never render the same message twice. */
  private swapOptimisticMessage(
    conversationId: string,
    optimisticId: string,
    real: ConversationMessage,
  ): void {
    this.mutateDetailForConversation(conversationId, (d) => {
      const alreadyPresent = d.messages.some((m) => m.id === real.id);
      const nextMessages = d.messages.reduce<ConversationMessage[]>((acc, m) => {
        if (m.id === optimisticId) {
          // If the real row landed via WS first, drop the placeholder.
          if (alreadyPresent) return acc;
          acc.push(real);
          return acc;
        }
        acc.push(m);
        return acc;
      }, []);
      return { ...d, messages: nextMessages };
    });
  }

  /** Drop an optimistic row on send failure. */
  private removeOptimisticMessage(conversationId: string, optimisticId: string): void {
    this.mutateDetailForConversation(conversationId, (d) => ({
      ...d,
      messages: d.messages.filter((m) => m.id !== optimisticId),
    }));
  }

  private bumpListLastMessage(id: string, isoTs: string): void {
    this.items.update((rows) =>
      rows
        .map((r) => (r.id === id ? { ...r, last_message_at: isoTs } : r))
        .sort((a, b) => {
          // Match the server's `ORDER BY last_message_at DESC NULLS LAST`.
          // Sorting on empty-string fallback made null rows leak to the
          // top of the list; explicit null sentinels keep client + server
          // rendering the same order.
          const av = a.last_message_at;
          const bv = b.last_message_at;
          if (av === bv) return 0;
          if (!av) return 1;
          if (!bv) return -1;
          return bv.localeCompare(av);
        }),
    );
  }
}

import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  DestroyRef,
  HostListener,
  ViewChild,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { ToastService } from '../../../../shared/components/toast/toast.service';
import { Subscription, of } from 'rxjs';
import { catchError, tap } from 'rxjs/operators';

import { ContactListItem, ContactsApiService } from '../contacts/contacts-api.service';
import { ConfirmDialogComponent } from '../shared/confirm-dialog/confirm-dialog.component';
import { MobileSelectComponent } from '../shared/forms/mobile-select.component';

import {
  Conversation,
  ConversationBulkAction,
  ConversationCounts,
  ConversationDetail,
  ConversationListQuery,
  ConversationMessage,
  ConversationStatus,
  ConversationTag,
  ConversationTagRef,
  ConversationsApiService,
} from './conversations-api.service';
import { SnoozePreset, snoozePresets } from './snooze-options';
import { TagChipComponent } from './tag-chip.component';
import { ChatThreadComponent } from './chat-thread.component';
import {
  ComposeBarComponent,
  ComposerEmailPayload,
  ComposerLocationPayload,
  ComposerMediaPayload,
  ComposerNotePayload,
} from './compose-bar.component';
import { ChatDetailsRailComponent } from './chat-details-rail.component';
import { ConversationListComponent } from './conversation-list.component';
import { InteractiveBuilderComponent, InteractivePayload } from './interactive-builder.component';
import { NewConversationModalComponent } from './new-conversation-modal.component';
import { WhatsAppTemplatePickerComponent } from './whatsapp-template-picker.component';
import { NotificationsApiService } from '../notifications/notifications-api.service';
import { UserMini, UsersDirectoryService } from '../shared/services/users-directory.service';
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
    ChatDetailsRailComponent,
    ComposeBarComponent,
    InteractiveBuilderComponent,
    NewConversationModalComponent,
    ReassignModalComponent,
    LucideAngularModule,
    MobileSelectComponent,
    WhatsAppTemplatePickerComponent,
    ConfirmDialogComponent,
    RouterLink,
    TagChipComponent,
  ],
  templateUrl: './conversations.page.html',
  host: { class: 'flex min-h-0 flex-1 flex-col' },
})
export class ConversationsPageComponent {
  private readonly api = inject(ConversationsApiService);
  private readonly notifications = inject(NotificationsApiService);
  private readonly usersDir = inject(UsersDirectoryService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  /** Zoneless CD: signal writes that fire from `setTimeout` /
   *  `setInterval` callbacks (the debounced WS reload + the 6-second
   *  open-thread poll) are outside any tracked reactive context and
   *  do not always wake the scheduler — the new detail lands in the
   *  signal but the thread doesn't repaint until the operator clicks
   *  or presses a key. `markForCheck()` after every async signal
   *  mutation closes that race. Same belt-and-braces pattern applied
   *  to the sibling `LeadFollowUpsPanel` / `TasksPanel`. */
  private readonly cdr = inject(ChangeDetectorRef);

  /** Step 27b — handle to the compose-bar so we can read its
   *  current Send-From selection on send. The picker self-hides
   *  for single-number orgs; the ViewChild stays defined either
   *  way (the compose-bar instance always exists when a
   *  conversation is open). */
  @ViewChild('composeBar') protected composeBar?: ComposeBarComponent;
  @ViewChild(ConversationListComponent) private readonly listCmp?: ConversationListComponent;

  /** Logged-in user id — drives the list component's "Mine" chip. */
  protected readonly currentUserId = this.auth.currentUserId;

  /** Wire value to hydrate the list's assignee chip with on first
   * render. Read from `sessionStorage` once; keyed by `org_id` so two
   * orgs the same user belongs to don't leak filters between sessions. */
  protected readonly initialAssignee = this.readPersistedAssignee();
  /** Same idea for the Unread chip so a refresh keeps it toggled. */
  protected readonly initialUnreadOnly = this.readPersistedUnread();

  protected readonly items = signal<Conversation[]>([]);
  /** True only while a (re)load runs against an EMPTY list (first load
   *  or a filter change). Background refreshes keep the rows painted. */
  protected readonly loading = signal(false);
  /** Refresh-button spinner — any list request in flight. */
  protected readonly refreshing = signal(false);
  protected readonly loadingMore = signal(false);
  /** Unread badge counts for the list's filter chips. */
  protected readonly counts = signal<ConversationCounts | null>(null);

  // --- Bulk selection --------------------------------------------------

  /** Conversations ticked in the list (bulk actions). */
  protected readonly bulkSelected = signal<ReadonlySet<string>>(new Set());
  protected readonly bulkBusy = signal(false);
  protected readonly bulkSnoozeOpen = signal(false);
  protected readonly bulkSnoozeChoices = signal<SnoozePreset[]>([]);
  protected readonly bulkTagOpen = signal(false);
  protected readonly bulkTags = signal<ConversationTag[]>([]);
  protected readonly bulkAssignOpen = signal(false);
  protected readonly bulkAssignError = signal<string | null>(null);
  /** One-click bulk actions rendered as icon buttons. */
  protected readonly bulkIconActions: ReadonlyArray<{
    action: ConversationBulkAction;
    label: string;
    icon: string;
  }> = [
    { action: 'mark_read', label: 'Mark as read', icon: 'check-check' },
    { action: 'mark_unread', label: 'Mark as unread', icon: 'mail' },
    { action: 'close', label: 'Close', icon: 'check-circle-2' },
    { action: 'reopen', label: 'Reopen', icon: 'circle-dot' },
  ];

  /** Server-side total for the active filters (drives "Load more"). */
  protected readonly total = signal(0);
  protected readonly hasMore = computed(() => this.items().length < this.total());
  /** Pages pulled so far — a background refresh re-fetches this many
   *  rows (capped by the API's 200 page size) so new inbound previews
   *  and unread badges stay current across everything on screen. */
  private loadedPages = 1;
  private static readonly LIST_PAGE_SIZE = 50;
  private static readonly LIST_MAX_PAGE_SIZE = 200;
  /** In-flight list request — cancelled when a newer one starts so a
   *  slow response can never overwrite fresher results. */
  private listSub: Subscription | null = null;
  /** Errors from the list / thread load paths. Rendered by the header
   *  banner. Cleared on next reload. */
  protected readonly loadError = signal<string | null>(null);
  /** Errors from send / patch / react actions. Rendered by the same
   *  banner but labelled per-action so a "Could not update reaction"
   *  toast doesn't read like a list-load failure. */
  protected readonly sendError = signal<string | null>(null);

  /** True when the current sendError is the backend's CAN-SPAM / DPDP
   *  refusal ("Your organisation has no physical address configured…").
   *  The template swaps in a friendlier banner + a direct CTA to
   *  Settings → Store Profile so the operator can fix the missing
   *  address in one click instead of parsing the raw 400. */
  protected readonly sendErrorNeedsStoreProfile = computed(() => {
    const err = this.sendError();
    return !!err && /physical address/i.test(err);
  });

  protected readonly selectedId = signal<string | null>(null);
  protected readonly detail = signal<ConversationDetail | null>(null);
  protected readonly threadLoading = signal(false);
  /** Older-history paging for the open thread. */
  protected readonly loadingOlder = signal(false);
  protected readonly hasOlder = signal(false);
  /** Mirrors the detail endpoint's first-page size (router.py). A first
   *  page shorter than this means the whole thread is already loaded. */
  private static readonly THREAD_PAGE_SIZE = 50;

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
   * via `GET /api/v1/users` (through `UsersDirectoryService` — the
   * shared cached lookup every other list page uses). We switched OFF
   * of `GET /api/v1/staff` because that endpoint is gated on
   * `staff.read` which the default Employee role doesn't hold, so
   * every assigned conversation rendered "Unknown user" at the
   * employee login. `users` is only gated on `get_current_user`
   * (any authenticated seat in the org) which is the correct
   * permission bar for a name-lookup. */
  protected readonly staffById = signal<Map<string, UserMini>>(new Map());

  /** Contact-name lookup for the list rows — resolves each row's
   *  `contact_id` to a display name so the list shows "Ananya Rao"
   *  instead of the raw phone/email `external_id`. Hydrated lazily
   *  after each `reloadList()`; already-fetched ids are skipped.
   *
   *  ``phone`` is cached here too so the chat header + details rail
   *  can render the contact's *current* phone instead of the
   *  ``external_id`` snapshot captured at inbound time — the raw
   *  snapshot goes stale the moment an operator adds a country code
   *  on the Contacts page (backend cascades the same edit onto live
   *  WhatsApp/SMS threads via
   *  ``conversations.service.resync_external_id_for_contact_phone``,
   *  but the fallback keeps the UI in sync for older stale rows too).
   */
  protected readonly contactsById = signal<
    Record<string, { id: string; full_name: string; phone: string | null }>
  >({});

  /** Step 13 — flat staff array for the @-mention picker in the
   *  composer. Derived from `staffById` (single source of truth). */
  protected readonly staffList = computed<UserMini[]>(() => Array.from(this.staffById().values()));

  /** When `true`, the reassign modal is rendered inline and bound to
   * `selectedConversation()`. Cancel/confirm flip it back to `false`. */
  protected readonly reassignOpen = signal(false);
  protected readonly reassignSubmitting = signal(false);
  protected readonly reassignError = signal<string | null>(null);

  /** When `true`, the new-conversation modal is mounted. The header
   *  `+ New` button opens it; the modal emits `started` (route to the
   *  fresh thread) or `cancel` (dismiss). */
  protected readonly newConversationOpen = signal(false);

  /** Mobile-only rail drawer. On <md screens the details rail
   *  collapses to keep the message column full-width; a "Details"
   *  button in the mobile back-strip flips this to render the rail
   *  as an off-canvas drawer. Auto-closes when the operator picks
   *  an action that opens a modal (reassign) or toggles AI, and on
   *  deselect / thread switch. */
  protected readonly mobileRailOpen = signal(false);

  protected openMobileRail(): void {
    this.mobileRailOpen.set(true);
  }

  protected closeMobileRail(): void {
    this.mobileRailOpen.set(false);
  }

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

  /** The open conversation. Prefers the list row (carries the preview
   *  + tags from the list payload) but falls back to the loaded detail
   *  so a thread that drops out of the current filter — e.g. marked
   *  read while the Unread chip is on, or deep-linked from a
   *  notification — stays open instead of blanking the chat pane. */
  protected readonly selectedConversation = computed<Conversation | null>(() => {
    const id = this.selectedId();
    if (!id) return null;
    const row = this.items().find((c) => c.id === id);
    if (row) return row;
    const d = this.detail();
    return d && d.conversation.id === id ? d.conversation : null;
  });

  /** Any list filter active — switches the list's empty state to
   *  "No matches · Clear filters". */
  protected readonly hasActiveFilters = computed(() => {
    const f = this.filters();
    return !!(
      f.channel ||
      f.status ||
      f.assigned_to ||
      f.q ||
      f.unread_only ||
      (f.tag_ids && f.tag_ids.length > 0)
    );
  });

  /** Header/rail counterparty label. Prefers the linked contact's
   *  *current* phone (kept fresh by the hydrated cache) over the
   *  conversation's stored ``external_id`` snapshot so a "+91" the
   *  operator just added on the Contacts page shows up here even on
   *  legacy rows that pre-date the backend cascade. Falls back to
   *  ``external_id`` for phone-less contacts (email threads, unlinked
   *  rows, or phone channels where the contact record has no phone
   *  yet). Only WhatsApp/SMS threads prefer the contact phone — email
   *  conversations keep showing the email ``external_id`` unchanged. */
  protected readonly selectedContactHandle = computed<string | null>(() => {
    const conv = this.selectedConversation();
    if (!conv) return null;
    if (conv.channel !== 'whatsapp' && conv.channel !== 'sms') {
      return conv.external_id ?? null;
    }
    const contact = conv.contact_id ? this.contactsById()[conv.contact_id] : undefined;
    const phone = contact?.phone?.trim();
    return phone && phone.length > 0 ? phone : (conv.external_id ?? null);
  });

  /** Linked contact's full name for the thread header. Null when the
   *  conversation isn't joined to a contact yet. Feeds the chat-thread
   *  header so the operator sees "Ajay" on top and
   *  "+91… · Whatsapp · Open" on the meta line beneath it. */
  protected readonly selectedContactName = computed<string | null>(() => {
    const conv = this.selectedConversation();
    if (!conv || !conv.contact_id) return null;
    const name = this.contactsById()[conv.contact_id]?.full_name?.trim();
    return name && name.length > 0 ? name : null;
  });

  /** View-only gate for the compose bar. Mirrors the backend
   * `ensure_can_write_conversation` rule (locked 2026-09-10) so the
   * operator sees the disabled state instead of hitting a 403 after
   * they try to send:
   *   - Owner / Admin (`conversations.assign_others`) → always true.
   *   - Chat unassigned → true (anyone can jump in; the send auto-
   *     claims the chat).
   *   - Caller is the current assignee → true.
   *   - Chat owned by someone else → false; compose-bar hides and
   *     the "assigned to X" view-only banner renders instead.
   *
   * The explicit "Take Over from AI" button in the chat-thread
   * header is scoped tighter (Owner/Admin only) — that's the "steal
   * another user's chat" motion the user restricted. */
  protected readonly canInteractWithSelected = computed(() => {
    const conv = this.selectedConversation();
    if (!conv) return false;
    if (this.auth.hasPermission('conversations.assign_others')) return true;
    const owner = conv.assigned_to_id ?? null;
    if (owner === null) return true;
    return owner === this.auth.currentUserId();
  });

  /** Display name of the current assignee — used in the view-only
   * banner ("Assigned to Ganesh Test · view-only"). */
  protected readonly selectedAssigneeName = computed<string | null>(() => {
    const conv = this.selectedConversation();
    const owner = conv?.assigned_to_id;
    if (!owner) return null;
    return this.staffById().get(owner)?.full_name ?? 'another user';
  });

  /** Last notification fingerprint we've already reacted to — guards
   * against re-running the refresh loop when the signal re-emits with
   * the same head element. */
  private lastSeenNotificationId: string | null = null;

  /** Coalesce bursty WS notifications (10 inbound msgs in one second)
   *  into a single list-reload + at-most-one thread-refresh per window.
   *  Without this every notification fires a full `GET /conversations`
   *  plus a `hydrateContacts` batch fetch. */
  private static readonly RELOAD_DEBOUNCE_MS = 300;
  private pendingListReloadTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingDetailReload: {
    id: string;
    timer: ReturnType<typeof setTimeout>;
  } | null = null;

  /** Fallback poll for the open thread. The WS-driven refresh only
   *  fires when `notify()` is called — the backend gates that behind
   *  `conversation.assigned_to_id is not None` and targets the
   *  assignee's user_id only. So an unassigned thread (or one owned
   *  by a different user) never pushes anything to this browser and
   *  inbound messages would sit invisible until manual refresh. This
   *  interval silently re-fetches the currently-open conversation so
   *  new inbound messages surface within one poll window regardless
   *  of the assignee state. Also re-loads the list at a slower cadence
   *  so row previews + unread badges keep pace. Pauses while the tab
   *  is hidden to avoid burning requests. */
  private static readonly OPEN_THREAD_POLL_MS = 6_000;
  private static readonly LIST_POLL_EVERY_N_TICKS = 3; // ≈ every 18s
  /** With no thread open, the list still refreshes on this cadence so
   *  new unassigned inbound conversations appear without a manual
   *  refresh (the WS push only reaches the assignee). */
  private static readonly IDLE_LIST_POLL_MS = 20_000;
  private openThreadPollTimer: ReturnType<typeof setInterval> | null = null;
  private openThreadPollTicks = 0;
  private idleListPollTimer: ReturnType<typeof setInterval> | null = null;
  private readonly onVisibilityChange = (): void => {
    if (document.visibilityState === 'visible') {
      // Regained focus — refresh immediately so the operator doesn't
      // wait a full tick before seeing what landed while they were away.
      const id = this.selectedId();
      if (id) {
        this.startOpenThreadPolling();
        this._reloadDetail(id);
      } else {
        this.startIdleListPolling();
      }
      this.reloadList();
    } else {
      this.stopOpenThreadPolling();
      this.stopIdleListPolling();
    }
  };

  /** AI take-over / return-to-AI confirmations. When set, the shared
   *  ConfirmDialogComponent renders — replaces the native ``confirm()``
   *  popups so the destructive-prompt UX matches the rest of the CRM
   *  (styled card, red button, submitting spinner). ``kind`` drives
   *  which title / body / verb the dialog shows. */
  protected readonly pendingAiConfirm = signal<{
    kind: 'takeover' | 'resume';
    conversationId: string;
  } | null>(null);
  protected readonly aiConfirmSubmitting = signal(false);

  constructor() {
    // Seed the filter from the persisted assignee + unread state BEFORE
    // the first list call so the request goes out with the right
    // `?assigned_to=…&unread_only=…` combination.
    const seed: ConversationListQuery = {};
    if (this.initialAssignee) seed.assigned_to = this.initialAssignee;
    if (this.initialUnreadOnly) seed.unread_only = true;
    if (Object.keys(seed).length > 0) this.filters.set(seed);
    this.reloadList({ reset: true });
    this.loadStaff();

    // Deep link: `/user/conversations?c=<id>` opens that thread (from a
    // notification, a shared link, or a refresh with a thread open).
    const deepLinkId = this.route.snapshot.queryParamMap.get('c');
    if (deepLinkId) {
      this.onSelect(deepLinkId);
    } else {
      this.startIdleListPolling();
    }

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

    // Live refresh: the backend pushes a non-persisted
    // `conversation.updated` event to every org member when a thread
    // changes (inbound message, bulk action). Coalesce bursts into one
    // list reload + one open-thread refresh.
    this.notifications.events$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((evt) => {
      if (evt.type !== 'conversation.updated') return;
      const ids = Array.isArray(evt.payload['conversation_ids'])
        ? (evt.payload['conversation_ids'] as unknown[]).filter(
            (v): v is string => typeof v === 'string',
          )
        : [];
      const open = this.selectedId();
      this.onIncomingNotification(
        open && ids.includes(open) ? { conversation_id: open } : { conversation_id: null },
      );
    });

    // Refresh whenever the browser tab regains focus. Even with the
    // interval below, a laptop lid re-opened after 10 minutes should
    // pull fresh state on the next paint rather than wait for the
    // tick after `visibilitychange` re-arms the interval.
    document.addEventListener('visibilitychange', this.onVisibilityChange);

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
      this.stopOpenThreadPolling();
      this.stopIdleListPolling();
      this.listSub?.unsubscribe();
      document.removeEventListener('visibilitychange', this.onVisibilityChange);
    });
  }

  /** One-shot staff load at page mount. Failure is non-fatal — badges
   * fall back to "?" initials and the neutral grey palette. */
  private loadStaff(): void {
    this.usersDir
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          const map = new Map<string, UserMini>();
          for (const r of rows) map.set(r.id, r);
          this.staffById.set(map);
          this.cdr.markForCheck();
        },
        error: () => {
          // Intentionally silent — page remains usable; the badge
          // markup degrades gracefully when the map is empty.
        },
      });
  }

  protected onFiltersChange(next: ConversationListQuery): void {
    // Preserve assigned_to + status across channel/q updates — the list
    // child owns channel + search + unread_only, the page header owns
    // status, so neither should clobber the other.
    const { assigned_to, status } = this.filters();
    this.filters.set({
      ...next,
      ...(assigned_to ? { assigned_to } : {}),
      ...(status ? { status } : {}),
    });
    this.persistUnread(next.unread_only ?? false);
    this.reloadList({ reset: true });
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
    this.reloadList({ reset: true });
  }

  protected onAssigneeFilterChange(value: string | undefined): void {
    this.filters.update((prev) => {
      const { assigned_to: _omit, ...rest } = prev;
      return value ? { ...rest, assigned_to: value } : rest;
    });
    this.persistAssignee(value);
    this.reloadList({ reset: true });
  }

  /** Empty-state "Clear filters": the list child already reset its
   *  chips; drop status + tags here and reload once. */
  protected onClearFilters(): void {
    this.statusFilter.set('');
    this.tagFilterIds.set([]);
    this.filters.set({});
    this.persistAssignee(undefined);
    this.persistUnread(false);
    this.reloadList({ reset: true });
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
    this.claimAssigneeOnSend(msg.conversation_id);
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
    this.reloadList({ reset: true });
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

  private unreadStorageKey(): string {
    const orgId = this.auth.currentOrg()?.id ?? 'anon';
    return `conversations:unread_only:${orgId}`;
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

  private readPersistedUnread(): boolean {
    try {
      return sessionStorage.getItem(this.unreadStorageKey()) === '1';
    } catch {
      return false;
    }
  }

  private persistUnread(on: boolean): void {
    try {
      if (on) sessionStorage.setItem(this.unreadStorageKey(), '1');
      else sessionStorage.removeItem(this.unreadStorageKey());
    } catch {
      // Best-effort; failure is silent.
    }
  }

  protected onSelect(id: string): void {
    if (id !== this.selectedId()) {
      // Reply targets belong to the thread they were picked in.
      this.replyingTo.set(null);
      this.sendError.set(null);
    }
    this.selectedId.set(id);
    this.loadDetail(id);
    this.stopIdleListPolling();
    this.startOpenThreadPolling();
    // Close the mobile rail if the operator flips to a different
    // conversation while it's open — the drawer is scoped to the
    // currently-selected conv and would look stale otherwise.
    this.mobileRailOpen.set(false);
    this.syncUrl(id);
  }

  /** Mobile back button — clears the selection so the list pane
   *  re-appears full-width on <md screens. Desktop keeps both panes
   *  visible so the button is hidden there. */
  protected deselect(): void {
    this.selectedId.set(null);
    this.detail.set(null);
    this.replyingTo.set(null);
    this.mobileRailOpen.set(false);
    this.stopOpenThreadPolling();
    this.startIdleListPolling();
    this.syncUrl(null);
  }

  /** Keep `?c=<id>` in the URL in step with the open thread (replace,
   *  not push — thread switches shouldn't flood browser history). */
  private syncUrl(id: string | null): void {
    if (this.route.snapshot.queryParamMap.get('c') === id) return;
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { c: id },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  private startIdleListPolling(): void {
    if (this.idleListPollTimer !== null) return;
    if (document.visibilityState !== 'visible') return;
    this.idleListPollTimer = setInterval(
      () => this.reloadList(),
      ConversationsPageComponent.IDLE_LIST_POLL_MS,
    );
  }

  private stopIdleListPolling(): void {
    if (this.idleListPollTimer !== null) {
      clearInterval(this.idleListPollTimer);
      this.idleListPollTimer = null;
    }
  }

  // --- Keyboard shortcuts ---------------------------------------------

  /** Inbox shortcuts (ignored while typing in a field or when a dialog
   *  is open):  j / k  next / previous conversation · /  search ·
   *  r  reply · n  internal note · Esc  close the mobile details drawer. */
  @HostListener('document:keydown', ['$event'])
  protected onGlobalKeydown(event: KeyboardEvent): void {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target as HTMLElement | null;
    const tag = target?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target?.isContentEditable) {
      return;
    }
    if (event.key === 'Escape') {
      if (this.mobileRailOpen()) this.closeMobileRail();
      else if (this.bulkSelected().size > 0 && !this.bulkAssignOpen()) this.clearBulkSelection();
      return;
    }
    if (
      this.bulkAssignOpen() ||
      this.reassignOpen() ||
      this.newConversationOpen() ||
      this.interactiveOpen() ||
      this.pendingAiConfirm()
    ) {
      return;
    }
    switch (event.key) {
      case 'j':
      case 'k':
        event.preventDefault();
        this.selectAdjacent(event.key === 'j' ? 1 : -1);
        break;
      case '/':
        event.preventDefault();
        this.listCmp?.focusSearch();
        break;
      case 'r':
      case 'n':
        if (this.composeBar) {
          event.preventDefault();
          this.composeBar.focusInput(event.key === 'r' ? 'reply' : 'note');
        }
        break;
    }
  }

  private selectAdjacent(step: 1 | -1): void {
    const rows = this.items();
    if (rows.length === 0) return;
    const idx = rows.findIndex((c) => c.id === this.selectedId());
    const next = idx === -1 ? (step === 1 ? 0 : rows.length - 1) : idx + step;
    if (next < 0 || next >= rows.length) return;
    const id = rows[next].id;
    this.onSelect(id);
    document.getElementById('conv-row-' + id)?.scrollIntoView({ block: 'nearest' });
  }

  private startOpenThreadPolling(): void {
    if (this.openThreadPollTimer !== null) return;
    if (!this.selectedId()) return;
    if (document.visibilityState !== 'visible') return;
    this.openThreadPollTicks = 0;
    this.openThreadPollTimer = setInterval(() => {
      const id = this.selectedId();
      if (!id) {
        this.stopOpenThreadPolling();
        return;
      }
      this._reloadDetail(id);
      this.openThreadPollTicks += 1;
      if (this.openThreadPollTicks % ConversationsPageComponent.LIST_POLL_EVERY_N_TICKS === 0) {
        this.reloadList();
      }
    }, ConversationsPageComponent.OPEN_THREAD_POLL_MS);
  }

  private stopOpenThreadPolling(): void {
    if (this.openThreadPollTimer !== null) {
      clearInterval(this.openThreadPollTimer);
      this.openThreadPollTimer = null;
    }
    this.openThreadPollTicks = 0;
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
        this.claimAssigneeOnSend(id);
        // Refresh the thread so the ``ai_paused`` flip (backend
        // auto-pauses on human reply when a bound assistant exists)
        // + the "AI is paused" system marker land immediately in the
        // UI. Without this the operator waits up to one poll window
        // (~6s) for the banner to swap from "AI is handling / Take
        // Over" to "You are handling / Return to AI".
        this._reloadDetail(id);
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
        // Never lose what the operator typed — put it back in the composer.
        this.composeBar?.restoreText(id, text);
        if (replyTarget && this.selectedId() === id && !this.replyingTo()) {
          this.replyingTo.set(replyTarget);
        }
      },
    });
  }

  /** Email reply with attachments. Optimistic bubble shows the text; the
   *  stored attachments appear when the server row swaps in. */
  protected onSendEmailWithFiles(payload: ComposerEmailPayload): void {
    const id = this.selectedId();
    if (!id) return;
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
      is_internal: false,
      mentioned_user_ids: [],
      is_ai: false,
      channel_message_id: null,
      sent_at: null,
      delivered_at: null,
      read_at: null,
      created_at: new Date().toISOString(),
    };
    this.detail.update((d) => (d ? { ...d, messages: [...d.messages, optimistic] } : d));
    this.api
      .sendEmailReplyWithAttachments(id, { bodyText: payload.text }, payload.files)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (real) => {
          this.swapOptimisticMessage(id, optimistic.id, real);
          this.bumpListLastMessage(id, real.sent_at ?? real.created_at);
          this.claimAssigneeOnSend(id);
        },
        error: (err: HttpErrorResponse) => {
          this.removeOptimisticMessage(id, optimistic.id);
          this.sendError.set(
            extractApiError(err) ??
              'Could not send this email. Check your connected mailbox and try again.',
          );
          this.composeBar?.restoreText(id, payload.text);
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
          this.composeBar?.restoreText(id, payload.text);
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
          this.claimAssigneeOnSend(id);
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
          this.claimAssigneeOnSend(id);
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
          this.claimAssigneeOnSend(id);
        },
        error: (err: HttpErrorResponse) => {
          this.removeOptimisticMessage(id, optimistic.id);
          this.sendError.set(extractApiError(err) ?? 'Could not send media.');
          if (payload.caption) this.composeBar?.restoreText(id, payload.caption);
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
          this.syncListRow(updated);
          this.detail.update((d) =>
            d && d.conversation.id === updated.id ? { ...d, conversation: updated } : d,
          );
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
          this.syncListRow(updated);
          this.detail.update((d) =>
            d && d.conversation.id === updated.id ? { ...d, conversation: updated } : d,
          );
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
    // Open the styled confirm dialog. Take-over is a claim of
    // responsibility for the thread (AI stops answering, this user
    // owns it) — worth a one-tap "yes I meant to do that" rather than
    // silently firing on click.
    this.pendingAiConfirm.set({ kind: 'takeover', conversationId: id });
  }

  protected onResumeAi(): void {
    const id = this.selectedId();
    if (!id) return;
    this.pendingAiConfirm.set({ kind: 'resume', conversationId: id });
  }

  protected cancelAiConfirm(): void {
    if (this.aiConfirmSubmitting()) return;
    this.pendingAiConfirm.set(null);
  }

  protected confirmAiAction(): void {
    const pending = this.pendingAiConfirm();
    if (!pending) return;
    this.aiConfirmSubmitting.set(true);
    if (pending.kind === 'takeover') {
      this._runTakeover(pending.conversationId);
    } else {
      this._runResume(pending.conversationId);
    }
  }

  // Copy driving the shared ConfirmDialog — computed getters so the
  // template can read the right title/body/verb per pending kind
  // without a big @switch on the caller side.
  protected aiConfirmTitle(): string {
    return this.pendingAiConfirm()?.kind === 'takeover'
      ? 'Take over from AI?'
      : 'Return this conversation to AI?';
  }

  protected aiConfirmBody(): string {
    return this.pendingAiConfirm()?.kind === 'takeover'
      ? 'AI will stop answering on this thread. You (and anyone you assign) will handle future messages until you hand it back.'
      : 'AI will handle future messages on this thread. Only the person who took over — or an admin — can do this.';
  }

  protected aiConfirmLabel(): string {
    return this.pendingAiConfirm()?.kind === 'takeover' ? 'Take over' : 'Return to AI';
  }

  private _runTakeover(id: string): void {
    this.api
      .pauseAi(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.syncListRow(updated);
          this.detail.update((d) =>
            d && d.conversation.id === updated.id ? { ...d, conversation: updated } : d,
          );
          this.toast.success('You took over from AI.');
          // Reload the thread so the freshly-inserted system marker
          // ("— {you} took over from AI —") lands in the UI without
          // needing a full page refresh.
          this._reloadDetail(id);
          this.aiConfirmSubmitting.set(false);
          this.pendingAiConfirm.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.aiConfirmSubmitting.set(false);
          this.pendingAiConfirm.set(null);
          if (err.status === 409) {
            const detail = err.error?.detail;
            const holder =
              (detail && typeof detail === 'object' && detail.holder_name) || 'Another user';
            this.toast.info(`${holder} just took this over.`);
            // Refresh so our local state matches the winner's.
            this._reloadDetail(id);
          } else {
            this.toast.error(extractApiError(err) ?? 'Could not take over.');
          }
        },
      });
  }

  private _runResume(id: string): void {
    this.api
      .resumeAi(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.syncListRow(updated);
          this.detail.update((d) =>
            d && d.conversation.id === updated.id ? { ...d, conversation: updated } : d,
          );
          this.toast.success('Returned to AI.');
          this._reloadDetail(id);
          this.aiConfirmSubmitting.set(false);
          this.pendingAiConfirm.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.aiConfirmSubmitting.set(false);
          this.pendingAiConfirm.set(null);
          const detail = err.error?.detail;
          if (err.status === 403 && detail?.reason === 'not_holder') {
            this.toast.warn('Only the person who took over (or an admin) can return this to AI.');
          } else {
            this.toast.error(extractApiError(err) ?? 'Could not return to AI.');
          }
        },
      });
  }

  private _reloadDetail(id: string): void {
    this.api
      .detail(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (fresh) => {
          // Guard: thread switch mid-fetch. Drop the response so we
          // don't paint stale content over the freshly-opened thread.
          if (this.selectedId() !== id) return;
          // MERGE — don't set(). A hard replace wipes any optimistic
          // ``tmp-...`` bubbles that are mid-send when the poll (or
          // WS-driven refresh) fires. The optimistic-swap that runs
          // after the POST returns then can't find its placeholder
          // and the sent message drops out of the UI until the next
          // fetch. Merging keeps optimistic bubbles until the server
          // supersedes them with a real row.
          //
          // The refresh only returns the newest page, so any older
          // history the operator scrolled up to load is kept too.
          this.detail.update((current) => {
            if (!current || current.conversation.id !== id) return fresh;
            const freshIds = new Set(fresh.messages.map((m) => m.id));
            const oldestFresh = fresh.messages[0];
            const oldestFreshAt = oldestFresh ? oldestFresh.created_at : null;
            const olderHistory = current.messages.filter(
              (m) =>
                !m.id.startsWith('tmp-') &&
                !freshIds.has(m.id) &&
                oldestFreshAt !== null &&
                m.created_at < oldestFreshAt,
            );
            const optimistic = current.messages.filter(
              (m) => m.id.startsWith('tmp-') && !freshIds.has(m.id),
            );
            if (olderHistory.length === 0 && optimistic.length === 0) return fresh;
            const tail = [...fresh.messages, ...optimistic].sort((a, b) => {
              const at = a.sent_at ?? a.created_at ?? '';
              const bt = b.sent_at ?? b.created_at ?? '';
              return at.localeCompare(bt);
            });
            return { ...fresh, messages: [...olderHistory, ...tail] };
          });
          this.syncListRow(fresh.conversation);
          this.cdr.markForCheck();
        },
        error: () => {
          /* silent — the takeover succeeded; the thread just won't
             re-render the system message until manual refresh. */
        },
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
      .pipe(tap(() => this.loadCounts()))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.syncListRow(updated);
          this.detail.update((d) =>
            d && d.conversation.id === updated.id ? { ...d, conversation: updated } : d,
          );
        },
        error: (err: HttpErrorResponse) => {
          this.sendError.set(extractApiError(err) ?? 'Could not update conversation status.');
        },
      });
  }

  /** Rail "Snooze until…" pick: ISO wake-up time or null (until reply). */
  protected onSnooze(until: string | null): void {
    const id = this.selectedId();
    if (!id) return;
    this.api
      .patch(id, { status: 'snoozed', snoozed_until: until })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.syncListRow(updated);
          this.detail.update((d) =>
            d && d.conversation.id === updated.id ? { ...d, conversation: updated } : d,
          );
          this.toast.success('Conversation snoozed.');
          this.loadCounts();
        },
        error: (err: HttpErrorResponse) => {
          this.sendError.set(extractApiError(err) ?? 'Could not snooze the conversation.');
        },
      });
  }

  // --- AI help (suggest reply / summarize) ------------------------------

  protected readonly aiSuggestBusy = signal(false);
  protected readonly summarizing = signal(false);
  /** Latest AI summary, pinned above the thread it belongs to. */
  protected readonly aiSummary = signal<{ conversationId: string; text: string } | null>(null);

  protected onAiSuggest(): void {
    const id = this.selectedId();
    if (!id || this.aiSuggestBusy()) return;
    this.aiSuggestBusy.set(true);
    this.api
      .aiAssist(id, 'suggest_reply')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ text }) => {
          this.aiSuggestBusy.set(false);
          this.composeBar?.applyAiDraft(id, text);
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.aiSuggestBusy.set(false);
          this.toast.error(extractApiError(err) ?? 'Could not draft a reply.');
          this.cdr.markForCheck();
        },
      });
  }

  protected onSummarize(): void {
    const id = this.selectedId();
    if (!id || this.summarizing()) return;
    this.summarizing.set(true);
    this.api
      .aiAssist(id, 'summarize')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ text }) => {
          this.summarizing.set(false);
          this.aiSummary.set({ conversationId: id, text });
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.summarizing.set(false);
          this.toast.error(extractApiError(err) ?? 'Could not summarize this conversation.');
          this.cdr.markForCheck();
        },
      });
  }

  /** In-flight flag for the details-rail contact card. */
  protected readonly contactBusy = signal(false);

  /** Contact card → "Save as contact" (`{ full_name }`) or "Link
   *  existing" (`{ contact_id }`). Swaps the updated conversation into
   *  the list + detail and hydrates the linked contact's name. */
  protected onSetContact(payload: { contact_id: string } | { full_name: string }): void {
    const id = this.selectedId();
    if (!id || this.contactBusy()) return;
    this.contactBusy.set(true);
    this.api
      .setContact(id, payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.contactBusy.set(false);
          this.syncListRow(updated);
          this.detail.update((d) =>
            d && d.conversation.id === updated.id ? { ...d, conversation: updated } : d,
          );
          this.hydrateContacts([updated]);
          this.toast.success('full_name' in payload ? 'Contact saved.' : 'Contact linked.');
        },
        error: (err: HttpErrorResponse) => {
          this.contactBusy.set(false);
          this.toast.error(extractApiError(err) ?? 'Could not save the contact.');
        },
      });
  }

  /** Contact card → rename the linked contact (typically replacing the
   *  "Unknown WhatsApp contact" placeholder). */
  protected onRenameContact(fullName: string): void {
    const contactId = this.selectedConversation()?.contact_id;
    if (!contactId || this.contactBusy()) return;
    this.contactBusy.set(true);
    this.contactsApi
      .update(contactId, { full_name: fullName })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (contact) => {
          this.contactBusy.set(false);
          this.contactsById.update((current) => ({
            ...current,
            [contact.id]: { id: contact.id, full_name: contact.full_name, phone: contact.phone },
          }));
          this.toast.success('Contact name updated.');
        },
        error: (err: HttpErrorResponse) => {
          this.contactBusy.set(false);
          this.toast.error(extractApiError(err) ?? 'Could not rename the contact.');
        },
      });
  }

  protected dismissSendError(): void {
    this.sendError.set(null);
  }

  /** Refresh the list. `reset` (filter change / first load) clears the
   *  rows and shows the skeleton; a plain refresh (polls, WS pushes,
   *  the Refresh button) re-fetches every loaded page silently so the
   *  list never flickers or loses its scroll position. */
  protected reloadList(opts: { reset?: boolean } = {}): void {
    const reset = !!opts.reset;
    if (reset) {
      this.loadedPages = 1;
      this.items.set([]);
      this.total.set(0);
      this.clearBulkSelection();
    }
    const { LIST_PAGE_SIZE, LIST_MAX_PAGE_SIZE } = ConversationsPageComponent;
    const size = Math.min(this.loadedPages * LIST_PAGE_SIZE, LIST_MAX_PAGE_SIZE);
    this.loading.set(this.items().length === 0);
    this.refreshing.set(true);
    this.loadingMore.set(false);
    this.loadError.set(null);
    this.listSub?.unsubscribe();
    this.listSub = this.api
      .list({ ...this.filters(), page: 1, size })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          // Rows loaded beyond the refresh window (> 200) are kept as-is.
          const freshIds = new Set(resp.items.map((r) => r.id));
          const beyond = this.items()
            .slice(size)
            .filter((r) => !freshIds.has(r.id));
          this.items.set([...resp.items, ...beyond]);
          this.total.set(resp.total);
          this.loading.set(false);
          this.refreshing.set(false);
          this.hydrateContacts(resp.items);
          this.pruneBulkSelection();
          this.loadCounts();
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.refreshing.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load conversations.');
          this.cdr.markForCheck();
        },
      });
  }

  private loadCounts(): void {
    this.api
      .counts()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (c) => {
          this.counts.set(c);
          this.cdr.markForCheck();
        },
        // Badges are decoration — keep the previous numbers on failure.
        error: () => undefined,
      });
  }

  // --- Bulk actions ------------------------------------------------------

  protected toggleBulkSelect(id: string): void {
    this.bulkSelected.update((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  protected selectAllVisible(): void {
    this.bulkSelected.set(new Set(this.items().map((c) => c.id)));
  }

  protected clearBulkSelection(): void {
    this.bulkSelected.set(new Set());
    this.bulkSnoozeOpen.set(false);
    this.bulkTagOpen.set(false);
  }

  /** Drop ticked ids that are no longer in the list (filter change). */
  private pruneBulkSelection(): void {
    const sel = this.bulkSelected();
    if (sel.size === 0) return;
    const visible = new Set(this.items().map((c) => c.id));
    const kept = [...sel].filter((id) => visible.has(id));
    if (kept.length !== sel.size) this.bulkSelected.set(new Set(kept));
  }

  protected openBulkSnooze(): void {
    this.bulkTagOpen.set(false);
    this.bulkSnoozeChoices.set(snoozePresets());
    this.bulkSnoozeOpen.update((v) => !v);
  }

  protected openBulkTag(): void {
    this.bulkSnoozeOpen.set(false);
    const opening = !this.bulkTagOpen();
    this.bulkTagOpen.set(opening);
    if (opening) {
      this.api
        .listTags()
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (tags) => {
            this.bulkTags.set(tags);
            this.cdr.markForCheck();
          },
          error: (err: HttpErrorResponse) => {
            this.bulkTagOpen.set(false);
            this.toast.error(extractApiError(err) ?? 'Could not load tags.');
          },
        });
    }
  }

  protected openBulkAssign(): void {
    this.bulkSnoozeOpen.set(false);
    this.bulkTagOpen.set(false);
    this.bulkAssignError.set(null);
    this.bulkAssignOpen.set(true);
  }

  protected runBulk(
    action: ConversationBulkAction,
    extra: { assigned_to_id?: string | null; tag_id?: string; snoozed_until?: string | null } = {},
  ): void {
    const ids = [...this.bulkSelected()];
    if (ids.length === 0 || this.bulkBusy()) return;
    this.bulkBusy.set(true);
    this.bulkSnoozeOpen.set(false);
    this.bulkTagOpen.set(false);
    this.api
      .bulk({ conversation_ids: ids, action, ...extra })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.bulkBusy.set(false);
          this.bulkAssignOpen.set(false);
          this.clearBulkSelection();
          const skipped = res.skipped.length;
          const done = `Updated ${res.updated} conversation${res.updated === 1 ? '' : 's'}.`;
          if (skipped > 0) {
            this.toast.warn(done, {
              subtitle: `${skipped} skipped — assigned to someone else or no longer available.`,
            });
          } else {
            this.toast.success(done);
          }
          this.reloadList();
          const open = this.selectedId();
          if (open && ids.includes(open)) this._reloadDetail(open);
        },
        error: (err: HttpErrorResponse) => {
          this.bulkBusy.set(false);
          const message = extractApiError(err) ?? 'Could not update the selected conversations.';
          if (this.bulkAssignOpen()) this.bulkAssignError.set(message);
          else this.toast.error(message);
          this.cdr.markForCheck();
        },
      });
  }

  protected onBulkAssignConfirm(payload: ReassignConfirm): void {
    this.runBulk('assign', { assigned_to_id: payload.userId });
  }

  /** Infinite scroll — append the next page. */
  protected loadMoreConversations(): void {
    if (this.loadingMore() || this.refreshing() || !this.hasMore()) return;
    const { LIST_PAGE_SIZE } = ConversationsPageComponent;
    const nextPage = Math.floor(this.items().length / LIST_PAGE_SIZE) + 1;
    this.loadingMore.set(true);
    this.listSub?.unsubscribe();
    this.listSub = this.api
      .list({ ...this.filters(), page: nextPage, size: LIST_PAGE_SIZE })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          const have = new Set(this.items().map((r) => r.id));
          const added = resp.items.filter((r) => !have.has(r.id));
          this.items.update((rows) => [...rows, ...added]);
          this.total.set(resp.total);
          this.loadedPages = nextPage;
          this.loadingMore.set(false);
          this.hydrateContacts(added);
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.loadingMore.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load more conversations.');
          this.cdr.markForCheck();
        },
      });
  }

  /** Patch a list row in place from a fresher server copy (thread
   *  refresh, mark-read) without refetching the whole list. Keeps the
   *  list-only fields (preview) the detail payload doesn't carry. */
  private syncListRow(conv: Conversation): void {
    this.items.update((rows) =>
      rows.map((r) =>
        r.id === conv.id
          ? { ...r, ...conv, last_message_body: conv.last_message_body ?? r.last_message_body }
          : r,
      ),
    );
  }

  /** Fetch contact rows for the currently-visible ``contact_id``s so
   *  the list can show the person's name instead of the raw
   *  `external_id`. Uses the batch ``POST /contacts/hydrate`` endpoint
   *  — one request for the whole page instead of one per row (the
   *  previous ``forkJoin(missing.map(get))`` fanned out 75+ XHRs on
   *  a full inbox and clogged the network waterfall). Failures are
   *  swallowed — missing contacts fall back to the external id in
   *  the template.
   *
   *  Refetches *every* visible contact each reload (not just uncached
   *  ones) so a contact edit made from the Contacts page — most
   *  commonly adding a "+91" prefix to a phone — propagates into the
   *  header/rail/list handle labels the next time this page pulls the
   *  inbox. One bulk POST per reload regardless of row count. */
  private hydrateContacts(rows: Conversation[]): void {
    const ids = new Set<string>();
    for (const r of rows) {
      if (r.contact_id) ids.add(r.contact_id);
    }
    const missing = [...ids];
    if (missing.length === 0) return;
    this.contactsApi
      .hydrateByIds(missing)
      .pipe(
        catchError(() => of([] as ContactListItem[])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((results) => {
        this.contactsById.update((current) => {
          const next = { ...current };
          for (const c of results) {
            next[c.id] = { id: c.id, full_name: c.full_name, phone: c.phone ?? null };
          }
          return next;
        });
        this.cdr.markForCheck();
      });
  }

  private loadDetail(id: string): void {
    this.threadLoading.set(true);
    this.loadingOlder.set(false);
    this.hasOlder.set(false);
    // Drop the previous thread immediately so its messages can never
    // flash under the newly-selected header.
    if (this.detail()?.conversation.id !== id) this.detail.set(null);
    this.api
      .detail(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (d) => {
          // Thread switched while this was in flight — drop it.
          if (this.selectedId() !== id) return;
          this.detail.set(d);
          this.hasOlder.set(d.messages.length >= ConversationsPageComponent.THREAD_PAGE_SIZE);
          this.threadLoading.set(false);
          this.syncListRow(d.conversation);
          this.cdr.markForCheck();
          // Opened a thread with an unread badge → clear it server-side
          // and zero the row locally (no full list reload — that used to
          // flicker the list and, with the Unread chip on, blank the
          // open thread). Best-effort: a failure leaves the badge lit.
          if ((d.conversation.unread_count ?? 0) > 0) {
            this.api
              .markRead(id)
              .pipe(takeUntilDestroyed(this.destroyRef))
              .subscribe({
                next: (updated) => {
                  this.syncListRow(updated);
                  this.detail.update((cur) =>
                    cur && cur.conversation.id === id
                      ? { ...cur, conversation: { ...cur.conversation, unread_count: 0 } }
                      : cur,
                  );
                  this.cdr.markForCheck();
                },
                error: () => undefined,
              });
          }
        },
        error: (err: HttpErrorResponse) => {
          if (this.selectedId() !== id) return;
          this.detail.set(null);
          this.threadLoading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load thread.');
          this.cdr.markForCheck();
        },
      });
  }

  /** Scroll-up paging: prepend the page older than the oldest loaded
   *  (non-optimistic) message. */
  protected onLoadOlder(): void {
    const id = this.selectedId();
    const d = this.detail();
    if (!id || !d || d.conversation.id !== id || this.loadingOlder() || !this.hasOlder()) return;
    const oldest = d.messages.find((m) => !m.id.startsWith('tmp-'));
    if (!oldest) return;
    const { THREAD_PAGE_SIZE } = ConversationsPageComponent;
    this.loadingOlder.set(true);
    this.api
      .loadOlderMessages(id, oldest.id, THREAD_PAGE_SIZE)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (older) => {
          this.loadingOlder.set(false);
          if (this.selectedId() !== id) return;
          this.hasOlder.set(older.length >= THREAD_PAGE_SIZE);
          this.mutateDetailForConversation(id, (cur) => {
            const have = new Set(cur.messages.map((m) => m.id));
            const add = older.filter((m) => !have.has(m.id));
            return add.length ? { ...cur, messages: [...add, ...cur.messages] } : cur;
          });
        },
        error: (err: HttpErrorResponse) => {
          this.loadingOlder.set(false);
          this.sendError.set(extractApiError(err) ?? 'Could not load earlier messages.');
          this.cdr.markForCheck();
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
    //
    // Uses ``_reloadDetail`` (silent refetch) rather than ``loadDetail``
    // — ``loadDetail`` toggles ``threadLoading=true`` which unmounts the
    // message list, replaces it with a "Loading thread…" placeholder,
    // and on remount the scroll position collapses to the top of the
    // rebuilt DOM. That flashed the thread back to older messages on
    // every WS-triggered refresh. Silent refetch keeps the bubbles
    // painted, appends the new one, and the chat-thread's own
    // ngAfterViewChecked scroll-to-bottom lands smoothly at the newest.
    if (incomingId && incomingId === this.selectedId()) {
      if (this.pendingDetailReload !== null) {
        clearTimeout(this.pendingDetailReload.timer);
      }
      const id = incomingId;
      const timer = setTimeout(() => {
        this.pendingDetailReload = null;
        // Guard against a thread switch during the debounce window.
        if (this.selectedId() === id) this._reloadDetail(id);
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
    this.cdr.markForCheck();
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

  /** Mirror the backend's implicit-claim on outbound send. When a
   *  human replies on an unassigned thread, ``send_outbound`` /
   *  ``send_email_reply`` set ``assigned_to_id = <sender>`` server-
   *  side. The optimistic-send path here only patches
   *  ``last_message_at``, so the assignee pill would stay
   *  "Unassigned" until a WS refresh landed. Patch both signals
   *  right after a successful send so the pill flips immediately
   *  and matches what the DB already reflects. */
  private claimAssigneeOnSend(conversationId: string): void {
    const me = this.auth.currentUserId();
    if (!me) return;
    const conv = this.items().find((c) => c.id === conversationId);
    if (!conv || conv.assigned_to_id) return;
    this.items.update((rows) =>
      rows.map((r) => (r.id === conversationId ? { ...r, assigned_to_id: me } : r)),
    );
    this.detail.update((d) =>
      d && d.conversation.id === conversationId
        ? { ...d, conversation: { ...d.conversation, assigned_to_id: me } }
        : d,
    );
    this.cdr.markForCheck();
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
    this.cdr.markForCheck();
  }
}

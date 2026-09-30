import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  EventEmitter,
  Input,
  Output,
  ViewChild,
  inject,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import {
  Conversation,
  ConversationChannel,
  ConversationCounts,
  ConversationListQuery,
} from './conversations-api.service';
import { UserMini } from '../shared/services/users-directory.service';
import { OwnerColor, ownerColor, staffInitials } from '../shared/owner-color.util';
import { ChannelBrandIconComponent } from './channel-brand-icon.component';
import { TagChipComponent } from './tag-chip.component';
import { TagFilterComponent } from './tag-filter.component';

interface ChannelBadgeStyle {
  label: string;
  bg: string;
  dot: string;
  /** Accent hue used when the pill is unselected (icon + dot). Selected
   * pills use the same hue as a filled background — see `channelPillClass`. */
  hue: 'emerald' | 'fuchsia' | 'blue' | 'zinc' | 'violet' | 'sky' | 'amber';
}

/**
 * Channel→style is one place — no per-channel branches scattered
 * across the page. Adding a new channel later is a single-line entry.
 */
const CHANNEL_STYLES: Record<ConversationChannel, ChannelBadgeStyle> = {
  whatsapp: {
    label: 'WhatsApp',
    bg: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20',
    dot: 'bg-emerald-500',
    hue: 'emerald',
  },
  instagram: {
    label: 'Instagram',
    bg: 'bg-fuchsia-500/10 text-fuchsia-400 ring-fuchsia-500/20',
    dot: 'bg-fuchsia-500',
    hue: 'fuchsia',
  },
  facebook: {
    label: 'Messenger',
    bg: 'bg-blue-500/10 text-blue-400 ring-blue-500/20',
    dot: 'bg-blue-500',
    hue: 'blue',
  },
  sms: {
    label: 'SMS',
    bg: 'bg-zinc-500/10 text-muted ring-zinc-500/20',
    dot: 'bg-zinc-400',
    hue: 'zinc',
  },
  email: {
    label: 'Email',
    bg: 'bg-violet-500/10 text-violet-400 ring-violet-500/20',
    dot: 'bg-violet-500',
    hue: 'violet',
  },
  web: {
    label: 'Web',
    bg: 'bg-sky-500/10 text-sky-400 ring-sky-500/20',
    dot: 'bg-sky-500',
    hue: 'sky',
  },
  ai_widget: {
    label: 'AI Widget',
    bg: 'bg-amber-500/10 text-amber-400 ring-amber-500/20',
    dot: 'bg-amber-500',
    hue: 'amber',
  },
};

interface ChannelPillOption {
  value: ConversationChannel | '';
  label: string;
  hue: 'emerald' | 'fuchsia' | 'blue' | 'zinc' | 'violet' | 'sky' | 'amber' | 'accent';
}

// v1 ships with WhatsApp + Email chips only. Messenger / Instagram /
// SMS / Web adapters exist in the backend but aren't wired for live
// ingest, so surfacing their chips would just show empty result sets
// and mislead users. Un-comment each entry as its ingest pipeline goes
// live (order here also drives the on-screen chip order).
//
// The ``ai_widget`` chip is intentionally omitted alongside those —
// legacy widget conversations still render in the ``All messengers``
// view (backend enum untouched), we just don't surface a dedicated
// filter chip while the widget stays a background surface.
const CHANNEL_PILL_OPTIONS: ChannelPillOption[] = [
  { value: '', label: 'All messengers', hue: 'accent' },
  { value: 'whatsapp', label: 'WhatsApp', hue: 'emerald' },
  { value: 'email', label: 'Email', hue: 'violet' },
  // { value: 'facebook', label: 'Messenger', hue: 'blue' },
  // { value: 'instagram', label: 'Instagram', hue: 'fuchsia' },
  // { value: 'sms', label: 'SMS', hue: 'zinc' },
  // { value: 'web', label: 'Web', hue: 'sky' },
];

/** Per-hue Tailwind class strings for the channel filter pill. Kept as
 * static maps so the classes are picked up by the compiler's static
 * analysis (dynamic string concat with a class name loses that). */
const PILL_ACTIVE_OUTLINE: Record<ChannelPillOption['hue'], string> = {
  accent: 'bg-accent/10 text-accent ring-accent',
  emerald: 'bg-emerald-500/10 text-emerald-700 ring-emerald-500 dark:text-emerald-300',
  fuchsia: 'bg-fuchsia-500/10 text-fuchsia-700 ring-fuchsia-500 dark:text-fuchsia-300',
  blue: 'bg-blue-500/10 text-blue-700 ring-blue-500 dark:text-blue-300',
  zinc: 'bg-zinc-500/10 text-zinc-700 ring-zinc-400 dark:text-zinc-200',
  violet: 'bg-violet-500/10 text-violet-700 ring-violet-500 dark:text-violet-300',
  sky: 'bg-sky-500/10 text-sky-700 ring-sky-500 dark:text-sky-300',
  amber: 'bg-amber-500/10 text-amber-700 ring-amber-500 dark:text-amber-300',
};

/** Solid brand-colour background for the small circular icon badge that
 * sits inside each channel pill. Icon inside is white. */
const PILL_BADGE_BG: Record<ChannelPillOption['hue'], string> = {
  accent: 'bg-accent',
  emerald: 'bg-emerald-500',
  fuchsia: 'bg-fuchsia-500',
  blue: 'bg-blue-500',
  zinc: 'bg-zinc-500',
  violet: 'bg-violet-500',
  sky: 'bg-sky-500',
  amber: 'bg-amber-500',
};

type AssigneeMode = 'all' | 'mine' | 'unassigned' | 'specific';

const ASSIGNEE_MODES: Array<{ value: AssigneeMode; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'mine', label: 'Mine' },
  { value: 'unassigned', label: 'Unassigned' },
];

@Component({
  selector: 'app-conversation-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ChannelBrandIconComponent, TagChipComponent, TagFilterComponent],
  templateUrl: './conversation-list.component.html',
  host: { class: 'flex min-h-0 flex-1 flex-col' },
})
export class ConversationListComponent {
  private readonly destroyRef = inject(DestroyRef);

  @Input() items: Conversation[] = [];
  /** First-load / filter-change load: the list body shows skeleton rows.
   *  Background refreshes never set this, so the list never flickers. */
  @Input() loading = false;
  /** True while more pages exist server-side (items.length < total). */
  @Input() hasMore = false;
  @Input() loadingMore = false;
  /** Any filter (search, channel, assignee, unread, tag, status) is
   *  active — switches the empty state to "no matches + Clear filters". */
  @Input() filtered = false;
  /** Unread badge counts for the filter chips (null until loaded). */
  @Input() counts: ConversationCounts | null = null;
  /** Bulk-selection set (owned by the page). Non-empty = selection mode:
   *  every row shows its checkbox. */
  @Input() selectedIds: ReadonlySet<string> = new Set();
  @Input() selectedId: string | null = null;
  @Input() staffById: Map<string, UserMini> = new Map();
  /** Contact-name lookup keyed by `contact_id`. Parent hydrates it
   *  after each list load; the row falls back to `external_id` when
   *  a contact hasn't been fetched yet (or is missing). ``phone`` is
   *  cached alongside the name so the row-handle line surfaces the
   *  contact's *current* phone (post-operator-edit) instead of the
   *  stale ``external_id`` snapshot on legacy rows. */
  @Input() contactsById: Record<string, { id: string; full_name: string; phone: string | null }> =
    {};
  /** UUID of the logged-in user — drives the "Mine" assignee chip.
   * Empty string means we don't yet know (auth still loading);
   * the "Mine" chip simply emits `undefined` in that case. */
  @Input() currentUserId: string = '';
  /** Hydrated by the parent from `sessionStorage` so a refresh keeps
   * the previously-active filter. `''` is treated as "All". */
  @Input() set initialAssignee(value: string) {
    this.applyHydratedAssignee(value);
  }
  /** Hydrates the Unread chip's on/off state on mount so a refresh
   *  keeps it toggled if the operator had it on. */
  @Input() set initialUnreadOnly(value: boolean) {
    this.unreadOnly.set(!!value);
  }

  @Output() readonly filtersChange = new EventEmitter<ConversationListQuery>();
  @Output() readonly select = new EventEmitter<string>();
  /** Emits the value that should be sent as `?assigned_to=…` on the
   * conversations list endpoint. `undefined` means "no filter" ("All"). */
  @Output() readonly assigneeChange = new EventEmitter<string | undefined>();
  /** Step 14 — emits the active tag-filter id array. Parent feeds
   *  this back into the list `tag_ids` query param (OR semantics). */
  @Output() readonly tagFilterChange = new EventEmitter<string[]>();
  /** Infinite scroll: operator reached the end of the loaded rows. */
  @Output() readonly loadMore = new EventEmitter<void>();
  /** "Clear filters" in the empty state. The list has already reset
   *  its own chips; the page resets status + tags and reloads once. */
  @Output() readonly clearFilters = new EventEmitter<void>();
  /** Row checkbox toggled. */
  @Output() readonly toggleSelect = new EventEmitter<string>();

  @ViewChild('searchInput') private readonly searchInput?: ElementRef<HTMLInputElement>;

  /** Keystrokes inside this window collapse into one list request. */
  private static readonly SEARCH_DEBOUNCE_MS = 300;
  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  /** Pixels from the bottom of the list that trigger the next page. */
  private static readonly LOAD_MORE_THRESHOLD_PX = 200;

  constructor() {
    this.destroyRef.onDestroy(() => {
      if (this.searchTimer) clearTimeout(this.searchTimer);
    });
  }

  /** Active tag-filter ids — hydrated by the parent so a refresh
   *  doesn't reset the filter. */
  @Input() tagFilterIds: string[] = [];

  protected readonly channelPillOptions = CHANNEL_PILL_OPTIONS;
  protected readonly assigneeModes = ASSIGNEE_MODES;

  /** Public (protected) so the template can read the signal directly for
   * the channel-pill active-state binding. */
  readonly channelFilter = signal<ConversationChannel | ''>('');
  /** Exposed to the template for the pill styling. */
  protected readonly pillActiveOutlineClass = PILL_ACTIVE_OUTLINE;
  protected readonly pillBadgeBgClass = PILL_BADGE_BG;
  protected readonly searchTerm = signal<string>('');
  protected readonly assigneeMode = signal<AssigneeMode>('all');
  /** Unread-only toggle chip — composes with the assignee filter so
   *  "Mine + Unread" and "Unassigned + Unread" both work. Hydrated by
   *  the parent from sessionStorage so a refresh keeps the state. */
  protected readonly unreadOnly = signal<boolean>(false);
  /** Set only via `applyHydratedAssignee` when a previously-saved
   *  `?assigned_to=<uuid>` value gets restored. `emitAssignee`
   *  forwards it to the parent so the filter stays applied across
   *  refresh even without a visible "Specific…" chip. */
  protected readonly specificUserId = signal<string | null>(null);

  protected channelStyle(channel: ConversationChannel): ChannelBadgeStyle {
    return CHANNEL_STYLES[channel];
  }

  /** Row display name.
   *
   * Priority:
   *   1. Real contact name when the contact has a human-typed name
   *      (not a placeholder auto-generated at inbound intake).
   *   2. "Unknown contact" fallback for placeholders whose full_name
   *      is just the phone (E.164) / email / matches the external_id.
   *      Those get created by ``ensure_placeholder_contact`` / the
   *      webhook resolver when an unknown number sends inbound, and
   *      surfacing them as "+919876543210" makes the inbox read like
   *      a raw phone list instead of a contact list.
   *   3. Raw ``external_id`` when there's no linked contact at all.
   */
  protected rowName(c: Conversation): string {
    if (c.contact_id) {
      const contact = this.contactsById[c.contact_id];
      if (contact) {
        const name = (contact.full_name ?? '').trim();
        if (name && !this.looksLikePlaceholderName(name, c.external_id)) {
          return name;
        }
        return 'Unknown contact';
      }
    }
    return c.external_id;
  }

  /** Secondary line under the display name — surfaces the raw
   *  channel-specific id (phone / email) whenever the primary label
   *  falls back to "Unknown contact" so the operator still sees the
   *  channel handle they need to identify the customer. Empty
   *  otherwise (avoids visual noise for named contacts).
   *
   *  For WhatsApp/SMS threads the linked contact's *current* phone is
   *  preferred over the ``external_id`` snapshot so an operator's
   *  "+91" edit on the Contacts page reflects in the inbox row even on
   *  legacy rows whose snapshot pre-dates the backend cascade in
   *  ``conversations.service.resync_external_id_for_contact_phone``. */
  protected rowHandle(c: Conversation): string {
    const name = this.rowName(c);
    const handle = this.contactPhoneOr(c);
    if (name === 'Unknown contact' || name === handle) return '';
    return handle;
  }

  /** Contact's current phone when the thread is on a phone channel and
   *  the linked contact carries a phone; else the raw ``external_id``.
   *  Kept private-ish (protected) so both ``rowHandle`` and future call
   *  sites read from a single source of truth. */
  protected contactPhoneOr(c: Conversation): string {
    if (c.channel === 'whatsapp' || c.channel === 'sms') {
      const contact = c.contact_id ? this.contactsById[c.contact_id] : undefined;
      const phone = contact?.phone?.trim();
      if (phone && phone.length > 0) return phone;
    }
    return c.external_id;
  }

  /** Heuristic for auto-generated placeholder names. Backend used to
   *  seed ``full_name = external_id`` (raw phone/email) or
   *  ``"Contact 3042"`` (last-4-digit stub) for unknown inbounds;
   *  new inbounds land as ``"Unknown WhatsApp contact"`` after the
   *  service-side rename, but old rows persist until edited. Any of
   *  those shapes → we treat the "name" as no name. */
  private looksLikePlaceholderName(name: string, externalId: string): boolean {
    if (name === externalId) return true;
    // Bare or +-prefixed E.164 numeric string.
    if (/^\+?\d{8,15}$/.test(name)) return true;
    // Email-shape.
    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(name)) return name === externalId;
    // "Contact 3042" last-4-digit stub from the chatbot placeholder path.
    if (/^Contact \d{4}$/.test(name)) return true;
    return false;
  }

  protected setChannelFilter(value: ConversationChannel | ''): void {
    this.channelFilter.set(value);
    this.emit();
  }

  /** Two-letter initials for the CONTACT the conversation is with —
   * this is what shows inside the avatar bubble. The assignee's initials
   * used to render here, which was misleading (customer "Priya" being
   * handled by staff "Rahul" would show "RA" under the name "Priya").
   * Standard inbox pattern: DP = contact, assignee shown separately.
   */
  protected contactInitials(c: Conversation): string {
    if (c.contact_id) {
      const contact = this.contactsById[c.contact_id];
      if (contact && contact.full_name) {
        const name = contact.full_name.trim();
        if (name && !this.looksLikePlaceholderName(name, c.external_id)) {
          return staffInitials(name);
        }
      }
    }
    // Fallback for placeholder / unknown contacts: first letter of the
    // channel handle (phone / email). Better than a raw '?' which reads
    // as a broken avatar.
    const handle = c.external_id?.trim() ?? '';
    if (handle) {
      const cleaned = handle.replace(/^[+\s]+/, '');
      if (cleaned) return cleaned[0].toUpperCase();
    }
    return '?';
  }

  /** Deterministic colour triple keyed off the contact id so the same
   * contact always renders the same avatar tint across the app. Falls
   * back to a neutral colour when the contact isn't linked yet. */
  protected contactColor(c: Conversation): OwnerColor {
    return ownerColor(c.contact_id);
  }

  /** Display name of the staff member currently assigned to the
   * conversation. Empty string when unassigned so the template can
   * render "Unassigned" in a dimmer style. */
  protected assigneeName(userId: string | null): string {
    if (!userId) return '';
    const staff = this.staffById.get(userId);
    return staff?.full_name ?? '';
  }

  protected formatTime(iso: string | null): string {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate();
    if (sameDay) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }

  protected onSearchInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.searchTerm.set(value);
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => {
      this.searchTimer = null;
      this.emit();
    }, ConversationListComponent.SEARCH_DEBOUNCE_MS);
  }

  /** `/` shortcut from the page. */
  public focusSearch(): void {
    this.searchInput?.nativeElement.focus();
    this.searchInput?.nativeElement.select();
  }

  protected onListScroll(event: Event): void {
    const el = event.target as HTMLElement;
    const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (
      remaining < ConversationListComponent.LOAD_MORE_THRESHOLD_PX &&
      this.hasMore &&
      !this.loadingMore
    ) {
      this.loadMore.emit();
    }
  }

  /** Reset every chip this component owns without emitting per-chip
   *  events, then hand off to the page for a single reload. */
  protected onClearFilters(): void {
    if (this.searchTimer) {
      clearTimeout(this.searchTimer);
      this.searchTimer = null;
    }
    this.searchTerm.set('');
    if (this.searchInput) this.searchInput.nativeElement.value = '';
    this.channelFilter.set('');
    this.unreadOnly.set(false);
    this.assigneeMode.set('all');
    this.specificUserId.set(null);
    this.clearFilters.emit();
  }

  /** Unread count for an assignee chip (All / Mine / Unassigned). */
  protected assigneeCount(mode: AssigneeMode): number {
    const c = this.counts;
    if (!c) return 0;
    return mode === 'mine' ? c.mine : mode === 'unassigned' ? c.unassigned : c.all;
  }

  protected channelCount(value: ConversationChannel | ''): number {
    const c = this.counts;
    if (!c) return 0;
    return value ? (c.by_channel[value] ?? 0) : c.all;
  }

  /** "Waiting 3h" — the customer spoke last, no AI is answering and the
   *  thread isn't closed. Empty string when nobody is waiting. */
  protected waitingLabel(c: Conversation): string {
    if (c.last_message_direction !== 'in' || c.ai_active || c.status === 'closed') return '';
    const since = c.last_customer_message_at ?? c.last_message_at;
    if (!since) return '';
    const minutes = Math.max(0, Math.floor((Date.now() - new Date(since).getTime()) / 60_000));
    if (minutes < 60) return `${Math.max(1, minutes)}m`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h`;
    return `${Math.floor(hours / 24)}d`;
  }

  /** Waiting for more than a day — label turns red. */
  protected waitingLong(c: Conversation): boolean {
    const since = c.last_customer_message_at ?? c.last_message_at;
    return !!since && Date.now() - new Date(since).getTime() > 24 * 60 * 60 * 1000;
  }

  protected onToggleSelect(event: Event, id: string): void {
    event.stopPropagation();
    this.toggleSelect.emit(id);
  }

  /** Stable DOM id so the page's j/k shortcut can scroll a row into view. */
  protected rowDomId(id: string): string {
    return 'conv-row-' + id;
  }

  protected pick(id: string): void {
    this.select.emit(id);
  }

  // --- Assignee chip --------------------------------------------------------

  protected setAssigneeMode(mode: AssigneeMode): void {
    this.assigneeMode.set(mode);
    if (mode !== 'specific') {
      this.specificUserId.set(null);
    }
    this.emitAssignee();
  }

  /** Compute the wire value for `?assigned_to=…` and emit it. */
  private emitAssignee(): void {
    const mode = this.assigneeMode();
    let value: string | undefined;
    switch (mode) {
      case 'mine':
        value = this.currentUserId || undefined;
        break;
      case 'unassigned':
        value = 'unassigned';
        break;
      case 'specific':
        value = this.specificUserId() ?? undefined;
        break;
      case 'all':
      default:
        value = undefined;
    }
    this.assigneeChange.emit(value);
  }

  /** Restore mode + specific id from a previously-persisted wire value. */
  private applyHydratedAssignee(value: string): void {
    if (!value) {
      this.assigneeMode.set('all');
      this.specificUserId.set(null);
      return;
    }
    if (value === 'unassigned') {
      this.assigneeMode.set('unassigned');
      this.specificUserId.set(null);
      return;
    }
    if (this.currentUserId && value === this.currentUserId) {
      this.assigneeMode.set('mine');
      this.specificUserId.set(null);
      return;
    }
    this.assigneeMode.set('specific');
    this.specificUserId.set(value);
  }

  protected toggleUnread(): void {
    this.unreadOnly.update((v) => !v);
    this.emit();
  }

  private emit(): void {
    const q: ConversationListQuery = {};
    if (this.channelFilter()) q.channel = this.channelFilter() as ConversationChannel;
    const term = this.searchTerm().trim();
    if (term) q.q = term;
    if (this.unreadOnly()) q.unread_only = true;
    this.filtersChange.emit(q);
  }
}

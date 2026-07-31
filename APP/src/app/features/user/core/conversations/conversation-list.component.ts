import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import {
  Conversation,
  ConversationChannel,
  ConversationListQuery,
} from './conversations-api.service';
import { StaffListItem } from '../staff/staff-api.service';
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
  hue: 'emerald' | 'fuchsia' | 'blue' | 'zinc' | 'violet' | 'sky';
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
};

interface ChannelPillOption {
  value: ConversationChannel | '';
  label: string;
  hue: 'emerald' | 'fuchsia' | 'blue' | 'zinc' | 'violet' | 'sky' | 'accent';
}

const CHANNEL_PILL_OPTIONS: ChannelPillOption[] = [
  { value: '', label: 'All messengers', hue: 'accent' },
  { value: 'whatsapp', label: 'WhatsApp', hue: 'emerald' },
  { value: 'facebook', label: 'Messenger', hue: 'blue' },
  { value: 'instagram', label: 'Instagram', hue: 'fuchsia' },
  { value: 'email', label: 'Email', hue: 'violet' },
  { value: 'sms', label: 'SMS', hue: 'zinc' },
  { value: 'web', label: 'Web', hue: 'sky' },
];

/** Per-hue Tailwind class strings for the channel filter pill. Kept as
 * static maps so the classes are picked up by the compiler's static
 * analysis (dynamic string concat with a class name loses that). */
const PILL_ACTIVE_OUTLINE: Record<ChannelPillOption['hue'], string> = {
  accent: 'bg-accent/10 text-accent ring-accent',
  emerald: 'bg-emerald-500/10 text-emerald-300 ring-emerald-500',
  fuchsia: 'bg-fuchsia-500/10 text-fuchsia-300 ring-fuchsia-500',
  blue: 'bg-blue-500/10 text-blue-300 ring-blue-500',
  zinc: 'bg-zinc-500/10 text-zinc-200 ring-zinc-400',
  violet: 'bg-violet-500/10 text-violet-300 ring-violet-500',
  sky: 'bg-sky-500/10 text-sky-300 ring-sky-500',
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
  @Input() items: Conversation[] = [];
  @Input() loading = false;
  @Input() selectedId: string | null = null;
  @Input() staffById: Map<string, StaffListItem> = new Map();
  /** Contact-name lookup keyed by `contact_id`. Parent hydrates it
   *  after each list load; the row falls back to `external_id` when
   *  a contact hasn't been fetched yet (or is missing). */
  @Input() contactsById: Record<string, { id: string; full_name: string }> = {};
  /** UUID of the logged-in user — drives the "Mine" assignee chip.
   * Empty string means we don't yet know (auth still loading);
   * the "Mine" chip simply emits `undefined` in that case. */
  @Input() currentUserId: string = '';
  /** Hydrated by the parent from `sessionStorage` so a refresh keeps
   * the previously-active filter. `''` is treated as "All". */
  @Input() set initialAssignee(value: string) {
    this.applyHydratedAssignee(value);
  }

  @Output() readonly filtersChange = new EventEmitter<ConversationListQuery>();
  @Output() readonly select = new EventEmitter<string>();
  /** Emits the value that should be sent as `?assigned_to=…` on the
   * conversations list endpoint. `undefined` means "no filter" ("All"). */
  @Output() readonly assigneeChange = new EventEmitter<string | undefined>();
  /** Step 14 — emits the active tag-filter id array. Parent feeds
   *  this back into the list `tag_ids` query param (OR semantics). */
  @Output() readonly tagFilterChange = new EventEmitter<string[]>();

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
  /** Set only via `applyHydratedAssignee` when a previously-saved
   *  `?assigned_to=<uuid>` value gets restored. `emitAssignee`
   *  forwards it to the parent so the filter stays applied across
   *  refresh even without a visible "Specific…" chip. */
  protected readonly specificUserId = signal<string | null>(null);

  protected channelStyle(channel: ConversationChannel): ChannelBadgeStyle {
    return CHANNEL_STYLES[channel];
  }

  /** Row display name: contact name when hydrated, else the raw
   *  channel-specific id (phone / email / handle). */
  protected rowName(c: Conversation): string {
    if (c.contact_id) {
      const contact = this.contactsById[c.contact_id];
      if (contact) return contact.full_name;
    }
    return c.external_id;
  }

  protected setChannelFilter(value: ConversationChannel | ''): void {
    this.channelFilter.set(value);
    this.emit();
  }

  /** Two-letter initials for the staff member that owns this thread,
   * or `·` if the thread is unassigned. */
  protected assigneeInitials(userId: string | null): string {
    if (!userId) return '·';
    const staff = this.staffById.get(userId);
    return staff ? staffInitials(staff.full_name) : '?';
  }

  /** Deterministic colour triple matching the same user id everywhere
   * else in the UI (leads kanban, appointments calendar, etc.). */
  protected assigneeColor(userId: string | null): OwnerColor {
    return ownerColor(userId);
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
    this.emit();
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

  private emit(): void {
    const q: ConversationListQuery = {};
    if (this.channelFilter()) q.channel = this.channelFilter() as ConversationChannel;
    const term = this.searchTerm().trim();
    if (term) q.q = term;
    this.filtersChange.emit(q);
  }
}

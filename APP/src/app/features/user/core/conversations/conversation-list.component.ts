import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import {
  Conversation,
  ConversationChannel,
  ConversationListQuery,
  ConversationStatus,
} from './conversations-api.service';
import { StaffListItem } from '../staff/staff-api.service';
import { OwnerColor, ownerColor, staffInitials } from '../shared/owner-color.util';
import { TagChipComponent } from './tag-chip.component';
import { TagFilterComponent } from './tag-filter.component';

interface ChannelBadgeStyle {
  label: string;
  bg: string;
  dot: string;
}

/**
 * Channel→style is one place — no per-channel branches scattered
 * across the page. Adding a new channel later is a single-line entry.
 */
const CHANNEL_STYLES: Record<ConversationChannel, ChannelBadgeStyle> = {
  whatsapp: {
    label: 'WhatsApp',
    bg: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    dot: 'bg-emerald-500',
  },
  instagram: {
    label: 'Instagram',
    bg: 'bg-gradient-to-r from-fuchsia-500 to-amber-400 text-white ring-fuchsia-200',
    dot: 'bg-fuchsia-500',
  },
  facebook: {
    label: 'Facebook',
    bg: 'bg-blue-50 text-blue-700 ring-blue-200',
    dot: 'bg-blue-500',
  },
  sms: {
    label: 'SMS',
    bg: 'bg-zinc-100 text-zinc-700 ring-zinc-200',
    dot: 'bg-zinc-500',
  },
  email: {
    label: 'Email',
    bg: 'bg-violet-50 text-violet-700 ring-violet-200',
    dot: 'bg-violet-500',
  },
  web: {
    label: 'Web',
    bg: 'bg-sky-50 text-sky-700 ring-sky-200',
    dot: 'bg-sky-500',
  },
};

const STATUS_OPTIONS: Array<{ value: ConversationStatus | ''; label: string }> = [
  { value: '', label: 'All statuses' },
  { value: 'open', label: 'Open' },
  { value: 'snoozed', label: 'Snoozed' },
  { value: 'closed', label: 'Closed' },
];

const CHANNEL_OPTIONS: Array<{ value: ConversationChannel | ''; label: string }> = [
  { value: '', label: 'All channels' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'email', label: 'Email' },
];

type AssigneeMode = 'all' | 'mine' | 'unassigned' | 'specific';

const ASSIGNEE_MODES: Array<{ value: AssigneeMode; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'mine', label: 'Mine' },
  { value: 'unassigned', label: 'Unassigned' },
  { value: 'specific', label: 'Specific…' },
];

@Component({
  selector: 'app-conversation-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, LucideAngularModule, TagChipComponent, TagFilterComponent],
  templateUrl: './conversation-list.component.html',
})
export class ConversationListComponent {
  @Input() items: Conversation[] = [];
  @Input() loading = false;
  @Input() selectedId: string | null = null;
  @Input() staffById: Map<string, StaffListItem> = new Map();
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

  protected readonly statusOptions = STATUS_OPTIONS;
  protected readonly channelOptions = CHANNEL_OPTIONS;
  protected readonly assigneeModes = ASSIGNEE_MODES;

  protected readonly channelFilter = signal<ConversationChannel | ''>('');
  protected readonly statusFilter = signal<ConversationStatus | ''>('');
  protected readonly searchTerm = signal<string>('');
  protected readonly assigneeMode = signal<AssigneeMode>('all');
  protected readonly specificUserId = signal<string | null>(null);

  /** Sorted list of staff names for the "Specific…" dropdown. */
  protected readonly staffOptions = computed<StaffListItem[]>(() =>
    Array.from(this.staffById.values()).sort((a, b) => a.full_name.localeCompare(b.full_name)),
  );

  protected readonly displayItems = computed(() => this.items);

  protected channelStyle(channel: ConversationChannel): ChannelBadgeStyle {
    return CHANNEL_STYLES[channel];
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

  protected onChannelChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value as ConversationChannel | '';
    this.channelFilter.set(value);
    this.emit();
  }

  protected onStatusChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value as ConversationStatus | '';
    this.statusFilter.set(value);
    this.emit();
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

  protected onSpecificUserChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value || null;
    this.specificUserId.set(value);
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
    if (this.statusFilter()) q.status = this.statusFilter() as ConversationStatus;
    const term = this.searchTerm().trim();
    if (term) q.q = term;
    this.filtersChange.emit(q);
  }
}

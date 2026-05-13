import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import {
  Conversation,
  ConversationChannel,
  ConversationListQuery,
  ConversationStatus,
} from './conversations-api.service';

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
  { value: 'instagram', label: 'Instagram' },
  { value: 'facebook', label: 'Facebook' },
  { value: 'sms', label: 'SMS' },
  { value: 'email', label: 'Email' },
  { value: 'web', label: 'Web' },
];

@Component({
  selector: 'app-conversation-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './conversation-list.component.html',
})
export class ConversationListComponent {
  @Input() items: Conversation[] = [];
  @Input() loading = false;
  @Input() selectedId: string | null = null;

  @Output() readonly filtersChange = new EventEmitter<ConversationListQuery>();
  @Output() readonly select = new EventEmitter<string>();

  protected readonly statusOptions = STATUS_OPTIONS;
  protected readonly channelOptions = CHANNEL_OPTIONS;

  protected readonly channelFilter = signal<ConversationChannel | ''>('');
  protected readonly statusFilter = signal<ConversationStatus | ''>('');
  protected readonly searchTerm = signal<string>('');

  protected readonly displayItems = computed(() => this.items);

  protected channelStyle(channel: ConversationChannel): ChannelBadgeStyle {
    return CHANNEL_STYLES[channel];
  }

  protected formatTime(iso: string | null): string {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear()
      && d.getMonth() === now.getMonth()
      && d.getDate() === now.getDate();
    if (sameDay) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }

  protected onChannelChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value as
      | ConversationChannel
      | '';
    this.channelFilter.set(value);
    this.emit();
  }

  protected onStatusChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value as
      | ConversationStatus
      | '';
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

  private emit(): void {
    const q: ConversationListQuery = {};
    if (this.channelFilter()) q.channel = this.channelFilter() as ConversationChannel;
    if (this.statusFilter()) q.status = this.statusFilter() as ConversationStatus;
    const term = this.searchTerm().trim();
    if (term) q.q = term;
    this.filtersChange.emit(q);
  }
}

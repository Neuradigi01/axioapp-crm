import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { Conversation, ConversationStatus, ConversationTagRef } from './conversations-api.service';
import { UserMini } from '../shared/services/users-directory.service';
import { OwnerColor, ownerColor, staffInitials } from '../shared/owner-color.util';
import { TagChipComponent } from './tag-chip.component';
import { TagManagerComponent } from './tag-manager.component';
import { ConversationBlockNumberActionComponent } from './header/block-number-action.component';
import { ConversationExportButtonComponent } from './header/export-button.component';
import { ConversationContactCardComponent } from './contact-card.component';
import { ContactActivityComponent } from './contact-activity.component';
import { SnoozePreset, formatHint, snoozePresets } from './snooze-options';
import { FurnitureAuthService } from '../auth/auth.service';

/**
 * Right-side details rail for a conversation. Intercom-style — every
 * bit of chrome that used to fight for space on the chat-thread's top
 * header (assignee pill, status pill+menu, tag manager, AI state pill,
 * Export, Block) moved to a vertical stack on the right so the middle
 * column can focus on messages.
 *
 * Pure UI move: the rail owns the local menu-open flags but every
 * mutation still flows via the same events (`reassign`, `statusChange`,
 * `tagsChanged`, `takeoverAi`, `resumeAiOut`) the page already wires
 * to its existing PATCH / POST handlers. Permission gates
 * (`canReassign` / `canTakeOver` / `canReturnToAi`) match the same
 * rules the chat-thread's inline banner has.
 */
@Component({
  selector: 'app-chat-details-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LucideAngularModule,
    TagChipComponent,
    TagManagerComponent,
    ConversationBlockNumberActionComponent,
    ConversationExportButtonComponent,
    ConversationContactCardComponent,
    ContactActivityComponent,
  ],
  templateUrl: './chat-details-rail.component.html',
  host: { class: 'flex min-h-0 flex-1 flex-col overflow-y-auto' },
})
export class ChatDetailsRailComponent {
  private readonly auth = inject(FurnitureAuthService);

  @Input({ required: true }) conversation!: Conversation;
  @Input() staffById: Map<string, UserMini> = new Map();

  /** Counterparty label rendered at the top of the rail. Parent page
   *  resolves this from the linked contact's *current* phone so an
   *  operator's "+91" prefix on the Contacts page reflects here even
   *  on legacy rows whose ``external_id`` snapshot pre-dates the
   *  backend cascade. Falls back to ``conversation.external_id``. */
  @Input() displayHandle: string | null = null;

  /** Linked contact's full name — rendered as the rail's primary
   *  heading with the handle demoted to the secondary line. Null when
   *  the conversation isn't joined to a contact; in that case the
   *  handle is promoted back to the primary heading. */
  @Input() contactName: string | null = null;

  /** True while the page's contact save / link / rename is in flight. */
  @Input() contactBusy = false;

  @Output() readonly reassign = new EventEmitter<void>();
  @Output() readonly tagsChanged = new EventEmitter<ConversationTagRef[]>();
  @Output() readonly statusChange = new EventEmitter<ConversationStatus>();
  /** Snooze picked from the status menu: ISO wake-up time, or null for
   *  "until the customer replies". */
  @Output() readonly snooze = new EventEmitter<string | null>();
  /** "Summarize with AI" clicked. */
  @Output() readonly summarize = new EventEmitter<void>();
  @Input() summarizing = false;
  /** Another conversation with the same contact was clicked. */
  @Output() readonly openConversation = new EventEmitter<string>();
  @Output() readonly takeoverAi = new EventEmitter<void>();
  @Output() readonly resumeAiOut = new EventEmitter<void>();
  @Output() readonly saveContact = new EventEmitter<string>();
  @Output() readonly linkContact = new EventEmitter<string>();
  @Output() readonly renameContact = new EventEmitter<string>();

  /** Channels whose ``external_id`` is a phone / email — the ones the
   *  contact card can save a new contact from. */
  protected hasContactIdentity(): boolean {
    const ch = this.conversation.channel;
    return ch === 'whatsapp' || ch === 'sms' || ch === 'email';
  }

  protected readonly statusMenuOpen = signal<boolean>(false);
  protected readonly tagManagerOpen = signal<boolean>(false);

  protected readonly canReassign = computed(() => {
    if (this.auth.hasPermission('conversations.assign_others')) return true;
    const me = this.auth.currentUserId();
    return !!me && this.conversation?.assigned_to_id === me;
  });

  protected readonly canTakeOver = computed(() =>
    this.auth.hasPermission('conversations.assign_others'),
  );

  protected readonly canReturnToAi = computed(() => {
    if (this.auth.hasPermission('conversations.assign_others')) return true;
    const holder = this.conversation?.ai_paused_by_user_id ?? null;
    const me = this.auth.currentUserId();
    return !!me && holder === me;
  });

  protected readonly statusLabel: Record<ConversationStatus, string> = {
    open: 'Open',
    snoozed: 'Snoozed',
    closed: 'Closed',
  };

  protected readonly statusOptions: readonly ConversationStatus[] = [
    'open',
    'snoozed',
    'closed',
  ] as const;

  protected toggleStatusMenu(): void {
    this.statusMenuOpen.update((v) => !v);
  }

  /** Snooze presets, recomputed each time the menu opens so "1 hour"
   *  is relative to now. */
  protected readonly snoozeChoices = signal<SnoozePreset[]>([]);
  protected readonly snoozeSubmenuOpen = signal(false);

  protected openSnoozeSubmenu(): void {
    this.snoozeChoices.set(snoozePresets());
    this.snoozeSubmenuOpen.set(true);
  }

  protected pickSnooze(preset: SnoozePreset): void {
    this.statusMenuOpen.set(false);
    this.snoozeSubmenuOpen.set(false);
    this.snooze.emit(preset.until ? preset.until.toISOString() : null);
  }

  /** "Until Tue 9:00" under the status pill for a timed snooze. */
  protected snoozedUntilLabel(): string | null {
    const iso = this.conversation.snoozed_until;
    if (this.conversation.status !== 'snoozed') return null;
    return iso ? `Until ${formatHint(new Date(iso))}` : 'Until the customer replies';
  }

  /** Outside click / Esc closes the status menu (the trigger and menu
   *  items stop propagation, so only genuine outside clicks land here). */
  @HostListener('document:click')
  @HostListener('document:keydown.escape')
  protected closeStatusMenu(): void {
    if (this.statusMenuOpen()) this.statusMenuOpen.set(false);
    this.snoozeSubmenuOpen.set(false);
  }

  protected pickStatus(next: ConversationStatus): void {
    if (next === 'snoozed') {
      this.openSnoozeSubmenu();
      return;
    }
    this.statusMenuOpen.set(false);
    this.snoozeSubmenuOpen.set(false);
    if (next === this.conversation.status) return;
    this.statusChange.emit(next);
  }

  protected toggleTagManager(): void {
    this.tagManagerOpen.update((v) => !v);
  }

  protected closeTagManager(): void {
    this.tagManagerOpen.set(false);
  }

  protected onTagsChanged(tags: ConversationTagRef[]): void {
    this.tagsChanged.emit(tags);
  }

  protected onTakeoverClick(): void {
    this.takeoverAi.emit();
  }

  protected onResumeClick(): void {
    this.resumeAiOut.emit();
  }

  protected staffInitialsFor(userId: string | null): string {
    if (!userId) return '·';
    const staff = this.staffById.get(userId);
    return staff ? staffInitials(staff.full_name) : '?';
  }

  protected staffNameFor(userId: string | null): string {
    if (!userId) return 'Unassigned';
    return this.staffById.get(userId)?.full_name ?? 'Unknown user';
  }

  protected staffColorFor(userId: string | null): OwnerColor {
    return ownerColor(userId);
  }
}

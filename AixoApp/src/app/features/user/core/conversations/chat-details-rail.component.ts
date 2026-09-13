import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { Conversation, ConversationStatus, ConversationTagRef } from './conversations-api.service';
import { StaffListItem } from '../staff/staff-api.service';
import { OwnerColor, ownerColor, staffInitials } from '../shared/owner-color.util';
import { TagChipComponent } from './tag-chip.component';
import { TagManagerComponent } from './tag-manager.component';
import { ConversationBlockNumberActionComponent } from './header/block-number-action.component';
import { ConversationExportButtonComponent } from './header/export-button.component';
import { AttributionChipComponent } from './header/attribution-chip.component';
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
    AttributionChipComponent,
  ],
  templateUrl: './chat-details-rail.component.html',
  host: { class: 'flex min-h-0 flex-1 flex-col overflow-y-auto' },
})
export class ChatDetailsRailComponent {
  private readonly auth = inject(FurnitureAuthService);

  @Input({ required: true }) conversation!: Conversation;
  @Input() staffById: Map<string, StaffListItem> = new Map();

  /** Counterparty label rendered at the top of the rail. Parent page
   *  resolves this from the linked contact's *current* phone so an
   *  operator's "+91" prefix on the Contacts page reflects here even
   *  on legacy rows whose ``external_id`` snapshot pre-dates the
   *  backend cascade. Falls back to ``conversation.external_id``. */
  @Input() displayHandle: string | null = null;

  @Output() readonly reassign = new EventEmitter<void>();
  @Output() readonly tagsChanged = new EventEmitter<ConversationTagRef[]>();
  @Output() readonly statusChange = new EventEmitter<ConversationStatus>();
  @Output() readonly takeoverAi = new EventEmitter<void>();
  @Output() readonly resumeAiOut = new EventEmitter<void>();

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

  protected pickStatus(next: ConversationStatus): void {
    this.statusMenuOpen.set(false);
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

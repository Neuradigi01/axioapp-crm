import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  ConversationTag,
  ConversationsApiService,
} from '../../conversations/conversations-api.service';
import { StaffApiService, StaffListItem } from '../../staff/staff-api.service';

import {
  AssignmentRule,
  AssignmentRuleUpsert,
  AssignmentStrategy,
  WhatsAppAutomationApiService,
} from './whatsapp-automation-api.service';

/**
 * Assignment rule editor (whatsapp-platform-upgrade Step 18).
 *
 * Strategy picker on the top; per-strategy config form below.
 * Submits the full rule on Save (the backend stores `config` as a
 * single JSONB so partial edits would be ambiguous).
 */
@Component({
  selector: 'app-assignment-rule-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  template: `
    <div class="space-y-4 rounded-md border border-subtle bg-surface p-4">
      <div class="flex items-center justify-between">
        <h3 class="text-base font-semibold text-default">
          {{ editingId() ? 'Edit assignment rule' : 'New assignment rule' }}
        </h3>
        <label class="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            [checked]="enabled()"
            (change)="enabled.set($any($event.target).checked)"
          />
          Enabled
        </label>
      </div>

      @if (error(); as msg) {
        <div class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {{ msg }}
        </div>
      }

      <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <label class="mb-1 block text-xs font-medium text-default">Name</label>
          <input
            type="text"
            [ngModel]="name()"
            (ngModelChange)="name.set($event)"
            maxlength="128"
            placeholder="Round-robin sales team"
            class="w-full rounded-md border border-subtle px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label class="mb-1 block text-xs font-medium text-default">Priority</label>
          <input
            type="number"
            [ngModel]="priority()"
            (ngModelChange)="priority.set($event)"
            min="0"
            max="10000"
            class="w-full rounded-md border border-subtle px-3 py-2 text-sm"
          />
        </div>
      </div>

      <div>
        <label class="mb-1 block text-xs font-medium text-default">Strategy</label>
        <div class="grid grid-cols-2 gap-2 md:grid-cols-4">
          @for (
            s of [
              { key: 'round_robin', label: 'Round-robin' },
              { key: 'load_balanced', label: 'Load-balanced' },
              { key: 'tag_based', label: 'Tag-based' },
              { key: 'team_based', label: 'Team-based' },
            ];
            track s.key
          ) {
            <button
              type="button"
              (click)="strategy.set($any(s.key))"
              [class]="
                'rounded-md border px-3 py-2 text-xs font-medium transition ' +
                (strategy() === s.key
                  ? 'border-accent bg-accent text-white'
                  : 'border-subtle bg-surface text-default hover:bg-surface-2')
              "
            >
              {{ s.label }}
            </button>
          }
        </div>
      </div>

      <!-- Per-strategy config -->
      @switch (strategy()) {
        @case ('round_robin') {
          <ng-container *ngTemplateOutlet="usersPicker" />
        }
        @case ('load_balanced') {
          <ng-container *ngTemplateOutlet="usersPicker" />
          <div>
            <label class="mb-1 block text-xs font-medium text-default">
              Cap per user (optional)
            </label>
            <input
              type="number"
              [ngModel]="capPerUser()"
              (ngModelChange)="capPerUser.set($event ? Number($event) : null)"
              min="1"
              placeholder="No cap"
              class="w-40 rounded-md border border-subtle px-3 py-2 text-sm"
            />
            <p class="mt-1 text-[10px] text-muted">
              Skip users with this many open conversations or more.
            </p>
          </div>
        }
        @case ('tag_based') {
          <div>
            <p class="mb-1 text-xs font-medium text-default">Tag → user mapping</p>
            <p class="mb-2 text-[10px] text-muted">
              When a new conversation has the tag, route it to the matching user.
            </p>
            <div class="space-y-2">
              @for (row of tagMapping(); track $index; let i = $index) {
                <div class="flex items-center gap-2">
                  <select
                    [ngModel]="row.tagId || null"
                    (ngModelChange)="updateTagMappingRow(i, 'tagId', $event)"
                    class="flex-1 rounded-md border border-subtle px-2 py-1.5 text-xs"
                  >
                    <option [ngValue]="null">— Pick a tag —</option>
                    @for (t of tags(); track t.id) {
                      <option [ngValue]="t.id">{{ t.name }}</option>
                    }
                  </select>
                  <span class="text-xs text-muted">→</span>
                  <select
                    [ngModel]="row.userId || null"
                    (ngModelChange)="updateTagMappingRow(i, 'userId', $event)"
                    class="flex-1 rounded-md border border-subtle px-2 py-1.5 text-xs"
                  >
                    <option [ngValue]="null">— Pick a user —</option>
                    @for (u of staff(); track u.id) {
                      <option [ngValue]="u.id">{{ u.full_name }}</option>
                    }
                  </select>
                  <button
                    type="button"
                    (click)="removeTagMappingRow(i)"
                    class="rounded p-1 text-muted hover:bg-surface-2"
                    aria-label="Remove row"
                  >
                    <lucide-icon name="x" size="12" />
                  </button>
                </div>
              }
              <button
                type="button"
                (click)="addTagMappingRow()"
                class="rounded-md border border-dashed border-subtle px-3 py-1.5 text-xs text-muted hover:bg-surface-2"
              >
                + Add mapping
              </button>
            </div>
          </div>
        }
        @case ('team_based') {
          <div>
            <p class="mb-1 text-xs font-medium text-default">Team</p>
            <p class="mb-2 text-[10px] text-muted">
              Teams are a placeholder — this strategy picks a random active org member until the
              teams concept lands. Enter any UUID for now (or use a different strategy).
            </p>
            <input
              type="text"
              [ngModel]="teamId()"
              (ngModelChange)="teamId.set($event)"
              placeholder="team UUID"
              class="w-full rounded-md border border-subtle px-3 py-2 text-sm"
            />
          </div>
        }
      }

      <label class="flex items-center gap-2 text-xs text-default">
        <input
          type="checkbox"
          [checked]="skipOutsideHours()"
          (change)="skipOutsideHours.set($any($event.target).checked)"
        />
        Skip outside business hours (uses the schedule on the Business Profile page)
      </label>

      <div class="flex items-center justify-end gap-2 border-t border-subtle pt-3">
        <button
          type="button"
          (click)="onCancel()"
          class="rounded-md border border-subtle bg-surface px-3 py-1.5 text-sm font-medium text-default hover:bg-surface-2"
        >
          Cancel
        </button>
        <button
          type="button"
          (click)="onSave()"
          [disabled]="saving()"
          class="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-white hover:bg-accent disabled:opacity-50"
        >
          {{ saving() ? 'Saving…' : editingId() ? 'Save changes' : 'Create rule' }}
        </button>
      </div>
    </div>

    <!-- Shared users picker used by round_robin + load_balanced -->
    <ng-template #usersPicker>
      <div>
        <p class="mb-1 text-xs font-medium text-default">Eligible users</p>
        <p class="mb-2 text-[10px] text-muted">
          Pick the staff who should receive new conversations.
        </p>
        <div class="space-y-1">
          @for (u of staff(); track u.id) {
            <label class="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                [checked]="isUserPicked(u.id)"
                (change)="toggleUser(u.id, $any($event.target).checked)"
              />
              <span>{{ u.full_name }}</span>
            </label>
          }
        </div>
      </div>
    </ng-template>
  `,
})
export class AssignmentRuleEditorComponent {
  private readonly api = inject(WhatsAppAutomationApiService);
  private readonly staffApi = inject(StaffApiService);
  private readonly conversationsApi = inject(ConversationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly Number = Number;

  @Input() set rule(value: AssignmentRule | null) {
    if (value) {
      this.editingId.set(value.id);
      this.name.set(value.name);
      this.strategy.set(value.strategy);
      this.enabled.set(value.enabled);
      this.priority.set(value.priority);
      this.skipOutsideHours.set(value.skip_outside_hours);
      this.hydrateConfig(value.strategy, value.config);
    } else {
      this.editingId.set(null);
      this.name.set('');
      this.strategy.set('round_robin');
      this.enabled.set(true);
      this.priority.set(100);
      this.skipOutsideHours.set(false);
      this.eligibleUserIds.set([]);
      this.capPerUser.set(null);
      this.tagMapping.set([]);
      this.teamId.set('');
    }
  }

  @Output() readonly saved = new EventEmitter<AssignmentRule>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly editingId = signal<string | null>(null);

  protected readonly name = signal<string>('');
  protected readonly strategy = signal<AssignmentStrategy>('round_robin');
  protected readonly enabled = signal<boolean>(true);
  protected readonly priority = signal<number>(100);
  protected readonly skipOutsideHours = signal<boolean>(false);

  protected readonly eligibleUserIds = signal<string[]>([]);
  protected readonly capPerUser = signal<number | null>(null);
  protected readonly tagMapping = signal<Array<{ tagId: string | null; userId: string | null }>>(
    [],
  );
  protected readonly teamId = signal<string>('');

  protected readonly staff = signal<StaffListItem[]>([]);
  protected readonly tags = signal<ConversationTag[]>([]);

  protected readonly saving = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);

  constructor() {
    this.staffApi
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.staff.set(rows),
        error: () => this.staff.set([]),
      });
    this.conversationsApi
      .listTags()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.tags.set(rows),
        error: () => this.tags.set([]),
      });
  }

  private hydrateConfig(strategy: AssignmentStrategy, config: Record<string, unknown>): void {
    if (strategy === 'round_robin' || strategy === 'load_balanced') {
      const raw = config['eligible_user_ids'];
      this.eligibleUserIds.set(Array.isArray(raw) ? (raw as unknown[]).map((u) => String(u)) : []);
      if (strategy === 'load_balanced') {
        const cap = config['cap_per_user'];
        this.capPerUser.set(typeof cap === 'number' ? cap : null);
      }
    } else if (strategy === 'tag_based') {
      const mapping = config['mapping'];
      if (mapping && typeof mapping === 'object' && !Array.isArray(mapping)) {
        this.tagMapping.set(
          Object.entries(mapping).map(([tagId, userId]) => ({
            tagId,
            userId: String(userId),
          })),
        );
      } else {
        this.tagMapping.set([]);
      }
    } else if (strategy === 'team_based') {
      this.teamId.set(String(config['team_id'] || ''));
    }
  }

  protected isUserPicked(id: string): boolean {
    return this.eligibleUserIds().includes(id);
  }

  protected toggleUser(id: string, checked: boolean): void {
    this.eligibleUserIds.update((arr) => (checked ? [...arr, id] : arr.filter((u) => u !== id)));
  }

  protected addTagMappingRow(): void {
    this.tagMapping.update((arr) => [...arr, { tagId: null, userId: null }]);
  }

  protected updateTagMappingRow(
    idx: number,
    field: 'tagId' | 'userId',
    value: string | null,
  ): void {
    this.tagMapping.update((arr) =>
      arr.map((row, i) => (i === idx ? { ...row, [field]: value } : row)),
    );
  }

  protected removeTagMappingRow(idx: number): void {
    this.tagMapping.update((arr) => arr.filter((_, i) => i !== idx));
  }

  protected onSave(): void {
    if (this.saving()) return;
    if (!this.name().trim()) {
      this.error.set('Name is required.');
      return;
    }
    const config = this.buildConfig();
    if (config === null) return; // error already set

    const payload: AssignmentRuleUpsert = {
      name: this.name().trim(),
      strategy: this.strategy(),
      config,
      enabled: this.enabled(),
      priority: this.priority(),
      skip_outside_hours: this.skipOutsideHours(),
    };
    this.saving.set(true);
    this.error.set(null);
    const id = this.editingId();
    const request$ = id
      ? this.api.updateAssignmentRule(id, payload)
      : this.api.createAssignmentRule(payload);
    request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (rule) => {
        this.saving.set(false);
        this.saved.emit(rule);
      },
      error: (err: HttpErrorResponse) => {
        this.saving.set(false);
        this.error.set(extractApiError(err) ?? 'Could not save the rule.');
      },
    });
  }

  protected onCancel(): void {
    this.cancel.emit();
  }

  private buildConfig(): Record<string, unknown> | null {
    const strategy = this.strategy();
    if (strategy === 'round_robin') {
      if (this.eligibleUserIds().length === 0) {
        this.error.set('Pick at least one user.');
        return null;
      }
      return { eligible_user_ids: this.eligibleUserIds() };
    }
    if (strategy === 'load_balanced') {
      if (this.eligibleUserIds().length === 0) {
        this.error.set('Pick at least one user.');
        return null;
      }
      return {
        eligible_user_ids: this.eligibleUserIds(),
        cap_per_user: this.capPerUser(),
      };
    }
    if (strategy === 'tag_based') {
      const mapping: Record<string, string> = {};
      for (const row of this.tagMapping()) {
        if (row.tagId && row.userId) {
          mapping[row.tagId] = row.userId;
        }
      }
      if (Object.keys(mapping).length === 0) {
        this.error.set('Add at least one tag → user mapping.');
        return null;
      }
      return { mapping };
    }
    // team_based
    if (!this.teamId().trim()) {
      this.error.set('Team UUID is required.');
      return null;
    }
    return { team_id: this.teamId().trim() };
  }
}

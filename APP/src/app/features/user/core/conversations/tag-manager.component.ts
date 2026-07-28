import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../auth/auth.service';
import {
  ConversationTag,
  ConversationTagRef,
  ConversationsApiService,
  TAG_COLOR_CLASSES,
  TAG_PALETTE,
  TagColor,
} from './conversations-api.service';
import { TagChipComponent } from './tag-chip.component';

/**
 * Tag manager dropdown (whatsapp-platform-upgrade Step 14).
 *
 * Opens from the conversation header's "Tags" button. Top section
 * lists currently-assigned tag chips (each with a × to unassign).
 * Below: search + tag list with "assign" buttons; users with
 * `settings.conversations.manage` see a `+ Create "<query>"` row when
 * the query has no exact match. Color swatch picker appears on
 * Create + Edit.
 *
 * Junior staff (no manage key) see only the picker + assign affordances;
 * the create / edit / delete buttons hide.
 */
@Component({
  selector: 'app-tag-manager',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule, TagChipComponent],
  template: `
    <div
      class="absolute right-0 top-full z-30 mt-1 w-72 rounded-md border border-subtle bg-surface shadow-lg"
      (click)="$event.stopPropagation()"
    >
      <div class="border-b border-subtle p-2">
        <p class="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">Applied</p>
        @if (assignedTags.length === 0) {
          <p class="text-xs text-muted">No tags yet.</p>
        } @else {
          <div class="flex flex-wrap gap-1">
            @for (t of assignedTags; track t.id) {
              <app-tag-chip [tag]="t" [removable]="true" (remove)="onUnassign($event)" />
            }
          </div>
        }
      </div>

      <div class="border-b border-subtle p-2">
        <div class="relative mb-1">
          <lucide-icon
            name="search"
            class="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-faint"
          />
          <input
            type="search"
            [ngModel]="query()"
            (ngModelChange)="onQueryChange($event)"
            placeholder="Search or create…"
            class="w-full rounded-md border border-subtle py-1 pl-7 pr-2 text-xs focus:border-muted focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>

        @if (loadError(); as err) {
          <p class="mb-1 text-[10px] text-rose-600">{{ err }}</p>
        }

        <ul class="max-h-48 space-y-0.5 overflow-y-auto">
          @for (t of filteredTags(); track t.id) {
            <li
              class="flex items-center justify-between gap-1 rounded px-1 py-0.5 hover:bg-surface-2"
            >
              <button
                type="button"
                (click)="onAssign(t)"
                [disabled]="isAssigned(t.id) || busyTagId() === t.id"
                class="flex flex-1 items-center gap-2 text-left text-xs disabled:opacity-40"
              >
                <span
                  [class]="'inline-block h-2.5 w-2.5 rounded-full ring-1 ' + swatchClass(t.color)"
                ></span>
                <span class="flex-1 truncate text-default">{{ t.name }}</span>
                <span class="text-[10px] text-faint">
                  {{ t.usage_count }}
                </span>
              </button>
              @if (canManage()) {
                <button
                  type="button"
                  (click)="onDelete(t)"
                  [disabled]="busyTagId() === t.id"
                  class="rounded p-0.5 text-faint hover:bg-rose-50 hover:text-rose-600 disabled:opacity-40"
                  title="Delete tag"
                  aria-label="Delete tag"
                >
                  <lucide-icon name="trash-2" size="10" />
                </button>
              }
            </li>
          }
        </ul>

        @if (canManage() && query().trim().length > 0 && !hasExactMatch()) {
          <div class="mt-2 rounded-md border border-dashed border-subtle p-2">
            <p class="mb-1 text-[10px] uppercase tracking-wide text-muted">
              Create "{{ query().trim() }}"
            </p>
            <div class="mb-1 flex flex-wrap gap-1">
              @for (c of TAG_PALETTE; track c) {
                <button
                  type="button"
                  (click)="newColor.set(c)"
                  [class]="
                    'h-4 w-4 rounded-full ring-1 ' +
                    swatchClass(c) +
                    (newColor() === c ? ' ring-zinc-900 ring-offset-1' : '')
                  "
                  [attr.aria-label]="'Color ' + c"
                ></button>
              }
            </div>
            <button
              type="button"
              (click)="onCreate()"
              [disabled]="creating()"
              class="w-full rounded-md bg-accent px-2 py-1 text-xs font-semibold text-white hover:bg-accent disabled:opacity-50"
            >
              {{ creating() ? 'Creating…' : 'Create + apply' }}
            </button>
          </div>
        }
      </div>

      <div class="flex justify-end p-2">
        <button
          type="button"
          (click)="close.emit()"
          class="rounded-md border border-subtle bg-surface px-2.5 py-1 text-xs font-medium text-default hover:bg-surface-2"
        >
          Close
        </button>
      </div>
    </div>
  `,
})
export class TagManagerComponent {
  private readonly api = inject(ConversationsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly TAG_PALETTE = TAG_PALETTE;

  @Input({ required: true }) conversationId!: string;
  @Input() assignedTags: ConversationTagRef[] = [];

  @Output() readonly close = new EventEmitter<void>();
  @Output() readonly tagsChanged = new EventEmitter<ConversationTagRef[]>();

  protected readonly tags = signal<ConversationTag[]>([]);
  protected readonly query = signal<string>('');
  protected readonly newColor = signal<TagColor>('zinc');
  protected readonly loadError = signal<string | null>(null);
  protected readonly creating = signal<boolean>(false);
  protected readonly busyTagId = signal<string | null>(null);

  protected readonly canManage = computed(() =>
    this.auth.hasPermission('settings.conversations.manage'),
  );

  protected readonly filteredTags = computed(() => {
    const q = this.query().trim().toLowerCase();
    const all = this.tags();
    return q.length === 0 ? all : all.filter((t) => t.name.toLowerCase().includes(q));
  });

  protected readonly hasExactMatch = computed(() => {
    const q = this.query().trim().toLowerCase();
    return this.tags().some((t) => t.name.toLowerCase() === q);
  });

  constructor() {
    this.reload();
  }

  private reload(): void {
    this.api
      .listTags()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.tags.set(rows),
        error: (err: HttpErrorResponse) =>
          this.loadError.set(extractApiError(err) ?? 'Could not load tags.'),
      });
  }

  protected onQueryChange(value: string): void {
    this.query.set(value);
  }

  protected swatchClass(color: string): string {
    return TAG_COLOR_CLASSES[color as TagColor] ?? TAG_COLOR_CLASSES.zinc;
  }

  protected isAssigned(tagId: string): boolean {
    return this.assignedTags.some((t) => t.id === tagId);
  }

  protected onAssign(tag: ConversationTag): void {
    if (this.isAssigned(tag.id)) return;
    this.busyTagId.set(tag.id);
    this.api
      .assignTag(this.conversationId, tag.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (tags) => {
          this.busyTagId.set(null);
          this.tagsChanged.emit(tags);
        },
        error: (err: HttpErrorResponse) => {
          this.busyTagId.set(null);
          this.loadError.set(extractApiError(err) ?? 'Could not assign tag.');
        },
      });
  }

  protected onUnassign(tagId: string): void {
    this.busyTagId.set(tagId);
    this.api
      .unassignTag(this.conversationId, tagId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (tags) => {
          this.busyTagId.set(null);
          this.tagsChanged.emit(tags);
        },
        error: (err: HttpErrorResponse) => {
          this.busyTagId.set(null);
          this.loadError.set(extractApiError(err) ?? 'Could not remove tag.');
        },
      });
  }

  protected onCreate(): void {
    if (!this.canManage()) return;
    const name = this.query().trim();
    if (!name) return;
    this.creating.set(true);
    this.api
      .createTag(name, this.newColor())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (tag) => {
          this.tags.update((arr) =>
            [...arr, { ...tag, usage_count: 0 }].sort((a, b) => a.name.localeCompare(b.name)),
          );
          // Immediately assign the newly-created tag.
          this.api
            .assignTag(this.conversationId, tag.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
              next: (tags) => {
                this.creating.set(false);
                this.tagsChanged.emit(tags);
                this.query.set('');
              },
              error: (err: HttpErrorResponse) => {
                this.creating.set(false);
                this.loadError.set(extractApiError(err) ?? 'Could not assign the new tag.');
              },
            });
        },
        error: (err: HttpErrorResponse) => {
          this.creating.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not create tag.');
        },
      });
  }

  protected onDelete(tag: ConversationTag): void {
    if (!this.canManage()) return;
    if (!confirm(`Delete tag "${tag.name}"? It will be removed from every conversation it's on.`)) {
      return;
    }
    this.busyTagId.set(tag.id);
    this.api
      .deleteTag(tag.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busyTagId.set(null);
          this.tags.update((arr) => arr.filter((t) => t.id !== tag.id));
          // Update the assigned list locally since the cascade also
          // dropped the assignment row server-side.
          const next = this.assignedTags.filter((t) => t.id !== tag.id);
          this.tagsChanged.emit(next);
        },
        error: (err: HttpErrorResponse) => {
          this.busyTagId.set(null);
          this.loadError.set(extractApiError(err) ?? 'Could not delete tag.');
        },
      });
  }
}

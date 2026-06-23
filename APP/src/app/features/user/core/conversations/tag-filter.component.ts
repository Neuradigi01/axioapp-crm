import { CommonModule } from '@angular/common';
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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import {
  ConversationTag,
  ConversationsApiService,
  TAG_COLOR_CLASSES,
  TagColor,
} from './conversations-api.service';

/**
 * Inbox tag filter (whatsapp-platform-upgrade Step 14).
 *
 * Multi-select chip dropdown — `(filterChange)` emits the active id
 * array, which the parent feeds into the list `tag_ids[]` query
 * param (OR semantics on the server).
 *
 * Visible whenever there's at least one tag in the org — falls back
 * to hidden when the library is empty (no point taking sidebar
 * real-estate for an empty filter).
 */
@Component({
  selector: 'app-tag-filter',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  template: `
    @if (tags().length > 0) {
      <div class="relative">
        <button
          type="button"
          (click)="toggleOpen()"
          [class]="
            'inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 transition ' +
            (selected().size > 0
              ? 'bg-zinc-900 text-white ring-zinc-900'
              : 'bg-white text-zinc-700 ring-zinc-300 hover:bg-zinc-50')
          "
        >
          <lucide-icon name="tag" size="11" />
          Tags
          @if (selected().size > 0) {
            <span class="ml-0.5 rounded-full bg-white/20 px-1 text-[10px]">
              {{ selected().size }}
            </span>
          }
        </button>

        @if (open()) {
          <div
            class="absolute right-0 top-full z-30 mt-1 w-56 rounded-md border border-zinc-200 bg-white p-1.5 shadow-lg"
            (click)="$event.stopPropagation()"
          >
            <ul class="max-h-60 space-y-0.5 overflow-y-auto">
              @for (t of tags(); track t.id) {
                <li>
                  <button
                    type="button"
                    (click)="toggleTag(t.id)"
                    [class]="
                      'flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-zinc-50 ' +
                      (selected().has(t.id) ? 'bg-zinc-50' : '')
                    "
                  >
                    <span
                      [class]="
                        'inline-block h-2.5 w-2.5 rounded-full ring-1 ' +
                        swatchClass(t.color)
                      "
                    ></span>
                    <span class="flex-1 truncate text-zinc-800">{{ t.name }}</span>
                    @if (selected().has(t.id)) {
                      <lucide-icon name="check" size="12" />
                    }
                  </button>
                </li>
              }
            </ul>
            @if (selected().size > 0) {
              <button
                type="button"
                (click)="clearAll()"
                class="mt-1 w-full rounded-md border border-zinc-300 bg-white px-2 py-1 text-[11px] font-medium text-zinc-700 hover:bg-zinc-50"
              >
                Clear ({{ selected().size }})
              </button>
            }
          </div>
        }
      </div>
    }
  `,
  host: {
    '(document:click)': 'closeOnOutside($event)',
  },
})
export class TagFilterComponent {
  private readonly api = inject(ConversationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** Currently-selected tag ids. Re-applied on input to keep the
   *  filter persistent across navigation. */
  @Input() set value(ids: string[]) {
    this.selected.set(new Set(ids));
  }

  @Output() readonly filterChange = new EventEmitter<string[]>();

  protected readonly tags = signal<ConversationTag[]>([]);
  protected readonly open = signal<boolean>(false);
  protected readonly selected = signal<Set<string>>(new Set());

  protected readonly count = computed(() => this.selected().size);

  constructor() {
    this.api
      .listTags()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.tags.set(rows),
        error: () => this.tags.set([]),
      });
  }

  protected toggleOpen(): void {
    this.open.update((v) => !v);
  }

  protected closeOnOutside(_event: Event): void {
    if (this.open()) this.open.set(false);
  }

  protected toggleTag(id: string): void {
    this.selected.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    this.filterChange.emit(Array.from(this.selected()));
  }

  protected clearAll(): void {
    this.selected.set(new Set());
    this.filterChange.emit([]);
  }

  protected swatchClass(color: string): string {
    return (
      TAG_COLOR_CLASSES[color as TagColor] ?? TAG_COLOR_CLASSES.zinc
    );
  }
}

import {
  CdkDrag,
  CdkDragDrop,
  CdkDropList,
  moveItemInArray,
} from '@angular/cdk/drag-drop';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { ColumnDef, ColumnPrefsService } from '../shared/column-prefs.service';

/**
 * Toolbar popover for showing/hiding and reordering table columns.
 *
 * The parent (`leads.page`) holds the canonical signal: this component
 * emits a brand-new array on every checkbox toggle, drag-drop, and
 * reset. The service is only touched here for the "reset to defaults"
 * link — the parent persists routine changes itself so the in-memory
 * signal and the storage entry never drift apart.
 */
@Component({
  selector: 'app-column-customization-menu',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, CdkDropList, CdkDrag],
  template: `
    <div class="relative inline-block">
      <button
        type="button"
        (click)="toggle()"
        [attr.aria-expanded]="open()"
        aria-haspopup="true"
        title="Customize columns"
        class="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 bg-white px-2.5 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50"
      >
        <lucide-icon name="columns-3" class="h-4 w-4" />
        <span class="sr-only">Customize columns</span>
      </button>

      @if (open()) {
        <div
          role="menu"
          class="absolute right-0 z-40 mt-1 w-64 origin-top-right rounded-md border border-zinc-200 bg-white shadow-lg ring-1 ring-black/5"
        >
          <div class="border-b border-zinc-100 px-3 py-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
            Columns
          </div>
          <ul
            cdkDropList
            (cdkDropListDropped)="onDrop($event)"
            class="max-h-72 overflow-y-auto py-1"
          >
            @for (col of columns(); track col.key) {
              <li
                cdkDrag
                class="flex cursor-grab items-center gap-2 px-3 py-1.5 text-sm text-zinc-700 hover:bg-zinc-50 active:cursor-grabbing"
              >
                <lucide-icon
                  name="grip-vertical"
                  class="h-4 w-4 flex-shrink-0 text-zinc-400"
                  cdkDragHandle
                />
                <label class="flex flex-1 cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    class="h-4 w-4 rounded border-zinc-300 text-zinc-900 focus:ring-zinc-500"
                    [checked]="col.visible"
                    (change)="onToggle(col.key, $any($event.target).checked)"
                  />
                  <span class="flex-1 truncate">{{ col.label }}</span>
                </label>
              </li>
            }
          </ul>
          <div class="flex items-center justify-between border-t border-zinc-100 px-3 py-2">
            <button
              type="button"
              (click)="onReset()"
              class="text-xs font-medium text-zinc-600 hover:text-zinc-900 hover:underline"
            >
              Reset to default
            </button>
            <button
              type="button"
              (click)="close()"
              class="text-xs font-medium text-zinc-500 hover:text-zinc-700"
            >
              Done
            </button>
          </div>
        </div>
      }
    </div>
  `,
})
export class ColumnCustomizationMenuComponent {
  private readonly columnPrefs = inject(ColumnPrefsService);
  private readonly hostRef = inject(ElementRef<HTMLElement>);

  /** Current ordered list of columns. The parent owns this; we mirror
   * it locally only to keep the popover snappy without triggering a
   * parent re-render on every drag-frame. */
  readonly columns = input.required<ColumnDef[]>();

  /** localStorage key suffix — usually a page identifier like `'leads'`.
   * The "Reset to default" link drops this entry. */
  readonly pageKey = input.required<string>();

  /** Defaults to restore when the user clicks "Reset to default." */
  readonly defaults = input.required<ColumnDef[]>();

  /** Emitted whenever the layout changes (visibility OR order). The
   * parent should call `columnPrefs.set(pageKey, cols)` itself so the
   * persisted state always matches what's on screen. */
  readonly columnsChange = output<ColumnDef[]>();

  protected readonly open = signal(false);

  protected toggle(): void {
    this.open.update((v) => !v);
  }

  protected close(): void {
    this.open.set(false);
  }

  /** Click-outside-to-close. */
  @HostListener('document:click', ['$event'])
  protected onDocumentClick(event: MouseEvent): void {
    if (!this.open()) return;
    const target = event.target as Node | null;
    if (target && !this.hostRef.nativeElement.contains(target)) {
      this.close();
    }
  }

  /** Esc closes the menu. */
  @HostListener('document:keydown.escape')
  protected onEsc(): void {
    if (this.open()) this.close();
  }

  protected onToggle(key: string, visible: boolean): void {
    const next = this.columns().map((c) =>
      c.key === key ? { ...c, visible } : { ...c },
    );
    this.columnsChange.emit(next);
  }

  protected onDrop(event: CdkDragDrop<ColumnDef[]>): void {
    if (event.previousIndex === event.currentIndex) return;
    const next = this.columns().map((c) => ({ ...c }));
    moveItemInArray(next, event.previousIndex, event.currentIndex);
    this.columnsChange.emit(next);
  }

  protected onReset(): void {
    this.columnPrefs.reset(this.pageKey());
    this.columnsChange.emit(this.defaults().map((c) => ({ ...c })));
  }
}

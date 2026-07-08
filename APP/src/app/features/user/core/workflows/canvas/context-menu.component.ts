import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  ViewChild,
  afterNextRender,
  effect,
  input,
  output,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

/**
 * Screen-space right-click menu for the workflow canvas.
 *
 * Rendered as a `position: fixed` overlay OUTSIDE the SVG zoom/pan group
 * so it never scales with the camera or clips against SVG bounds. A
 * full-viewport transparent backdrop captures outside interaction:
 * left-click or right-click on the backdrop closes; Escape closes too.
 *
 * The menu box measures itself after render and flips horizontally /
 * vertically when the requested anchor would push it off-screen, so it
 * always stays fully visible regardless of where the click landed.
 */

export interface ContextMenuItem {
  /** Stable action id emitted on `select`. */
  id: string;
  label: string;
  /** Lucide icon name; omit for a text-only row. */
  icon?: string;
  /** Renders in rose and separated as a destructive action. */
  danger?: boolean;
  /** Greyed-out, non-selectable. */
  disabled?: boolean;
  /** Draws a divider ABOVE this item. */
  separatorBefore?: boolean;
}

@Component({
  selector: 'app-context-menu',
  standalone: true,
  imports: [CommonModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="fixed inset-0 z-[60]"
      (mousedown)="onBackdropDown($event)"
      (contextmenu)="onBackdropContext($event)"
    >
      <div
        #menu
        class="absolute min-w-[168px] py-1 bg-white border border-zinc-200 rounded-lg shadow-lg text-sm text-zinc-700 select-none"
        [style.left.px]="pos().left"
        [style.top.px]="pos().top"
        (contextmenu)="$event.preventDefault()"
      >
        @for (item of items(); track item.id) {
          @if (item.separatorBefore) {
            <div class="my-1 h-px bg-zinc-100"></div>
          }
          <button
            type="button"
            class="flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            [class.text-rose-600]="item.danger && !item.disabled"
            [class.hover:bg-rose-50]="item.danger && !item.disabled"
            [class.hover:bg-zinc-100]="!item.danger && !item.disabled"
            [disabled]="item.disabled"
            (click)="onSelect(item)"
          >
            @if (item.icon) {
              <lucide-icon [name]="item.icon" class="w-4 h-4 shrink-0"></lucide-icon>
            }
            <span class="flex-1">{{ item.label }}</span>
          </button>
        }
      </div>
    </div>
  `,
})
export class ContextMenuComponent {
  readonly x = input.required<number>();
  readonly y = input.required<number>();
  readonly items = input.required<ContextMenuItem[]>();

  readonly menuSelect = output<string>();
  readonly menuClose = output<void>();

  @ViewChild('menu', { static: false })
  menuRef?: ElementRef<HTMLDivElement>;

  /** Adjusted client-space position after edge-flipping. */
  readonly pos = signal<{ left: number; top: number }>({ left: 0, top: 0 });

  constructor() {
    // Seed the anchor immediately so the first paint is close; refine
    // once we can measure the rendered box.
    effect(() => this.pos.set({ left: this.x(), top: this.y() }));
    afterNextRender(() => this.reposition());
  }

  private reposition(): void {
    const el = this.menuRef?.nativeElement;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const margin = 8;
    let left = this.x();
    let top = this.y();
    if (left + rect.width > window.innerWidth - margin) {
      left = Math.max(margin, window.innerWidth - rect.width - margin);
    }
    if (top + rect.height > window.innerHeight - margin) {
      top = Math.max(margin, window.innerHeight - rect.height - margin);
    }
    this.pos.set({ left, top });
  }

  onSelect(item: ContextMenuItem): void {
    if (item.disabled) return;
    this.menuSelect.emit(item.id);
    this.menuClose.emit();
  }

  onBackdropDown(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      this.menuClose.emit();
    }
  }

  onBackdropContext(event: MouseEvent): void {
    // Swallow the native menu on the backdrop and dismiss.
    event.preventDefault();
    this.menuClose.emit();
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.menuClose.emit();
  }
}

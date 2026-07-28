import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { CatalogTile } from './onboarding.types';

/**
 * One pack tile in the onboarding picker grid.
 *
 * Renders icon + name + description + (optional) "Coming soon" badge.
 * Emits `select` with the template_id when the user clicks an *available*
 * tile. Coming-soon tiles are visually dimmed and not clickable.
 */
@Component({
  selector: 'app-pack-tile',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  template: `
    <button
      type="button"
      [class]="rootClasses()"
      [disabled]="tile().status !== 'available'"
      (click)="onClick()"
      [attr.aria-pressed]="selected()"
    >
      @if (tile().status === 'coming_soon') {
        <span
          class="absolute top-2 right-2 text-[10px] font-medium uppercase tracking-wide bg-surface-2 text-default px-2 py-0.5 rounded-full"
        >
          Coming soon
        </span>
      }
      @if (selected()) {
        <span
          class="absolute top-2 right-2 inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-600 text-white"
        >
          <lucide-icon name="check" class="w-4 h-4"></lucide-icon>
        </span>
      }

      <div
        class="flex items-center justify-center w-12 h-12 rounded-lg bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400 mb-3"
      >
        <lucide-icon [name]="tile().icon" class="w-6 h-6"></lucide-icon>
      </div>

      <div class="text-base font-semibold text-default mb-1">
        {{ tile().name }}
      </div>
      <div class="text-sm text-muted leading-snug line-clamp-2">
        {{ tile().description }}
      </div>
    </button>
  `,
})
export class PackTileComponent {
  readonly tile = input.required<CatalogTile>();
  readonly selected = input<boolean>(false);
  readonly select = output<string>();

  protected readonly rootClasses = computed(() => {
    const base =
      'relative flex flex-col items-start text-left rounded-xl border bg-surface p-5 transition w-full h-full';
    const t = this.tile();
    if (t.status !== 'available') {
      return `${base} border-subtle opacity-60 cursor-not-allowed`;
    }
    if (this.selected()) {
      return `${base} border-blue-600 ring-2 ring-blue-500 shadow-md`;
    }
    return `${base} border-subtle cursor-pointer hover:border-blue-400 dark:hover:border-blue-500 hover:shadow-md`;
  });

  protected onClick(): void {
    if (this.tile().status === 'available') {
      this.select.emit(this.tile().template_id);
    }
  }
}

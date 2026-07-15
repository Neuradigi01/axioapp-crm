import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  HostListener,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import {
  TemplateChannel,
  TemplateRead,
  TemplatesApiService,
} from '../../templates/templates-api.service';

/**
 * Template picker modal — opened from the editor's "Pick template"
 * button. Reuses the central `TemplatesApiService` so the editor
 * doesn't duplicate the template-list query.
 *
 * Filters by:
 *   - the trigger's chosen channel (required input)
 *   - `internal_status='published'` always
 *   - `external_status='approved'` ONLY when channel='whatsapp'
 *     (other channels don't have a meaningful external_status —
 *     n_a is acceptable)
 *
 * Each row carries "Open in editor" so the operator can pop the
 * template into a new tab for editing without losing the
 * automation editor's state. Selecting a row emits `picked` with
 * the chosen template + closes via `closed`.
 */
@Component({
  selector: 'app-template-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, RouterLink, LucideAngularModule],
  templateUrl: './template-picker.component.html',
})
export class TemplatePickerComponent {
  private readonly api = inject(TemplatesApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly channel = input.required<TemplateChannel>();

  readonly picked = output<TemplateRead>();
  readonly closed = output<void>();

  protected readonly items = signal<TemplateRead[]>([]);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly searchQuery = signal<string>('');

  protected readonly filtered = computed<TemplateRead[]>(() => {
    const q = this.searchQuery().trim().toLowerCase();
    if (!q) return this.items();
    return this.items().filter((t) => t.name.toLowerCase().includes(q));
  });

  constructor() {
    effect(() => {
      const channel = this.channel();
      this.reload(channel);
    });
  }

  private reload(channel: TemplateChannel): void {
    this.loading.set(true);
    this.loadError.set(null);
    const query: Parameters<TemplatesApiService['list']>[0] = {
      channel,
      internal_status: 'published',
      limit: 100,
    };
    if (channel === 'whatsapp') {
      query.external_status = 'approved';
    }
    this.api
      .list(query)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.items.set(res.items);
          this.loading.set(false);
        },
        error: () => {
          this.items.set([]);
          this.loading.set(false);
          this.loadError.set('Could not load templates.');
        },
      });
  }

  protected onSearch(value: string): void {
    this.searchQuery.set(value);
  }

  protected onPick(t: TemplateRead): void {
    this.picked.emit(t);
    this.closed.emit();
  }

  protected onClose(): void {
    this.closed.emit();
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    this.onClose();
  }
}

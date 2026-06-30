import { CommonModule, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../auth/auth.service';

import { ChannelChipComponent } from '../templates/channel-chip.component';
import { EventTypeChipComponent } from './event-type-chip.component';
import {
  AutomationsApiService,
  EventCatalogEntry,
  TriggerChannel,
  TriggerRead,
} from './automations-api.service';

/**
 * Automations list page — first frontend surface of the
 * single-event trigger engine (`tasks/automation-engine` Step 7).
 *
 * Filters: event-type (populated from the discovery endpoint),
 * channel, enabled toggle, search. Inline enable/disable toggle on
 * every row hits the dedicated POST endpoint + optimistically
 * updates the local row so the operator sees the flip without a
 * full re-fetch. Pagination is server-side (limit / offset).
 *
 * "New automation" button is gated on `automations.write`;
 * Employees see read-only list + can navigate to /user/templates
 * via the per-row template name link.
 */

const PAGE_SIZE = 25;

const CHANNEL_OPTIONS: Array<{ value: '' | TriggerChannel; label: string }> = [
  { value: '', label: 'All channels' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'email', label: 'Email' },
  { value: 'sms', label: 'SMS' },
  { value: 'facebook', label: 'Facebook Messenger' },
  { value: 'instagram', label: 'Instagram Direct' },
  { value: 'push', label: 'Push notification' },
];

const ENABLED_OPTIONS: Array<{ value: '' | 'true' | 'false'; label: string }> = [
  { value: '', label: 'All triggers' },
  { value: 'true', label: 'Enabled only' },
  { value: 'false', label: 'Disabled only' },
];

@Component({
  selector: 'app-automations-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    DatePipe,
    LucideAngularModule,
    ChannelChipComponent,
    EventTypeChipComponent,
  ],
  templateUrl: './automations.page.html',
})
export class AutomationsPageComponent {
  private readonly api = inject(AutomationsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly CHANNEL_OPTIONS = CHANNEL_OPTIONS;
  protected readonly ENABLED_OPTIONS = ENABLED_OPTIONS;
  protected readonly PAGE_SIZE = PAGE_SIZE;

  // List state.
  protected readonly items = signal<TriggerRead[]>([]);
  protected readonly total = signal<number>(0);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly pageIndex = signal<number>(0);

  // Event-type discovery (Step-3 endpoint).
  protected readonly eventCatalog = signal<EventCatalogEntry[]>([]);

  // Filters.
  protected readonly eventFilter = signal<string>('');
  protected readonly channelFilter = signal<'' | TriggerChannel>('');
  protected readonly enabledFilter = signal<'' | 'true' | 'false'>('');
  protected readonly searchQuery = signal<string>('');
  protected readonly debouncedSearch = signal<string>('');

  // Per-row toggle state — keyed by trigger id. While a toggle is
  // in flight the row's checkbox is disabled to avoid double-clicks.
  protected readonly togglingIds = signal<Set<string>>(new Set());

  protected readonly canWrite = computed(() => this.auth.hasPermission('automations.write'));

  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / PAGE_SIZE)));
  protected readonly hasPrev = computed(() => this.pageIndex() > 0);
  protected readonly hasNext = computed(() => this.pageIndex() < this.totalPages() - 1);

  private searchTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    // One-shot load of the event-type catalog at page mount.
    this.api
      .listEventTypes()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (entries) => this.eventCatalog.set(entries),
        error: () => {
          // Non-fatal — the dropdown just stays empty + the
          // operator types the event_type manually in the editor
          // (Step 8). The list page's filter UI also falls back to
          // a plain text input.
        },
      });

    // Re-fetch on every filter / page change.
    effect(() => {
      const event = this.eventFilter();
      const channel = this.channelFilter();
      const enabled = this.enabledFilter();
      const q = this.debouncedSearch();
      const page = this.pageIndex();
      void event;
      void channel;
      void enabled;
      void q;
      void page;
      this.reload();
    });
  }

  // --- filters / search -----------------------------------------------

  protected onEventChange(value: string): void {
    this.eventFilter.set(value);
    this.pageIndex.set(0);
  }

  protected onChannelChange(value: string): void {
    this.channelFilter.set(value as '' | TriggerChannel);
    this.pageIndex.set(0);
  }

  protected onEnabledChange(value: string): void {
    this.enabledFilter.set(value as '' | 'true' | 'false');
    this.pageIndex.set(0);
  }

  protected onSearchInput(value: string): void {
    this.searchQuery.set(value);
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => {
      this.debouncedSearch.set(value.trim());
      this.pageIndex.set(0);
    }, 300);
  }

  protected clearFilters(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.eventFilter.set('');
    this.channelFilter.set('');
    this.enabledFilter.set('');
    this.searchQuery.set('');
    this.debouncedSearch.set('');
    this.pageIndex.set(0);
  }

  // --- pagination -----------------------------------------------------

  protected nextPage(): void {
    if (this.hasNext()) this.pageIndex.update((p) => p + 1);
  }

  protected prevPage(): void {
    if (this.hasPrev()) this.pageIndex.update((p) => p - 1);
  }

  // --- inline toggle --------------------------------------------------

  protected isToggling(id: string): boolean {
    return this.togglingIds().has(id);
  }

  protected onToggleEnabled(row: TriggerRead): void {
    if (!this.canWrite() || this.isToggling(row.id)) return;
    const next = !row.enabled;
    const ids = new Set(this.togglingIds());
    ids.add(row.id);
    this.togglingIds.set(ids);

    const call = next ? this.api.enable(row.id) : this.api.disable(row.id);
    call.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (updated) => {
        // Optimistic update — patch the local row without a full reload.
        this.items.update((rows) => rows.map((r) => (r.id === row.id ? updated : r)));
        this.endToggle(row.id);
      },
      error: (err: HttpErrorResponse) => {
        this.endToggle(row.id);
        this.loadError.set(extractApiError(err) ?? 'Could not change trigger state.');
      },
    });
  }

  private endToggle(id: string): void {
    const ids = new Set(this.togglingIds());
    ids.delete(id);
    this.togglingIds.set(ids);
  }

  // --- fetch ----------------------------------------------------------

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    const offset = this.pageIndex() * PAGE_SIZE;
    const enabledFilter = this.enabledFilter();
    const enabled = enabledFilter === 'true' ? true : enabledFilter === 'false' ? false : undefined;
    this.api
      .list({
        event_type: this.eventFilter() || undefined,
        channel: this.channelFilter() || undefined,
        enabled,
        q: this.debouncedSearch() || undefined,
        limit: PAGE_SIZE,
        offset,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.items.set(res.items);
          this.total.set(res.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.total.set(0);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load automations.');
        },
      });
  }

  protected trackById = (_: number, row: TriggerRead) => row.id;
}

/**
 * Step 8 — Dead-letter queue table (inline expandable).
 *
 * Loaded on first visibility (parent toggles `visible` input).
 * Columns:
 *   - Time (relative)
 *   - Provider tag
 *   - Error message (truncated)
 *   - Retries attempted
 *   - Replay / Discard buttons
 *
 * Replay POSTs to `/dlq/{id}/replay` — row stays in the list with
 * `replayed_at` stamped + `replayed_by=<actor>`. Discard POSTs to
 * `/dlq/{id}/discard` — row stays with `replayed_at` stamped +
 * `replayed_by=NULL` (the discriminator).
 *
 * After either action: refetch the page so the row's "Replayed" /
 * "Discarded" pill renders correctly. The status panel above also
 * refreshes via its 30s poll.
 *
 * Pagination: server-side, size=20, simple prev/next. No bulk select
 * in v1 — spec excludes bulk replay.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  IntegrationDLQRow,
  IntegrationProvider,
  IntegrationsApiService,
} from './integrations-api.service';


const PAGE_SIZE = 20;


@Component({
  selector: 'app-dlq-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './dlq-list.component.html',
})
export class DlqListComponent {
  /** Parent toggles to true when the status banner is clicked. The
   *  effect below triggers the first fetch on the transition. */
  readonly visible = input<boolean>(false);

  /** Emitted after replay/discard so the parent can also refresh
   *  the status panel + integrations list (open DLQ count drops). */
  readonly changed = output<void>();

  private readonly api = inject(IntegrationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly rows = signal<IntegrationDLQRow[]>([]);
  protected readonly total = signal(0);
  protected readonly page = signal(1);
  protected readonly providerFilter = signal<IntegrationProvider | ''>('');
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  /** dlq-id of an in-flight Replay/Discard so we can disable both
   *  buttons on that row while the request resolves. */
  protected readonly actionInFlight = signal<string | null>(null);

  protected readonly totalPages = computed(() =>
    Math.max(1, Math.ceil(this.total() / PAGE_SIZE)),
  );

  constructor() {
    // Lazy load: only fetch when the panel is visible. Refetch on
    // page / filter change.
    effect(() => {
      if (!this.visible()) return;
      // Reading these signals registers the effect dependency.
      this.page();
      this.providerFilter();
      this._fetch();
    });
  }

  // --- handlers ----------------------------------------------------

  setProvider(p: IntegrationProvider | ''): void {
    if (this.providerFilter() === p) return;
    this.providerFilter.set(p);
    this.page.set(1);
  }

  prevPage(): void {
    if (this.page() <= 1) return;
    this.page.update((p) => p - 1);
  }

  nextPage(): void {
    if (this.page() >= this.totalPages()) return;
    this.page.update((p) => p + 1);
  }

  replay(row: IntegrationDLQRow): void {
    if (this.actionInFlight()) return;
    if (row.replayed_at !== null) return;
    this.actionInFlight.set(row.id);
    this.error.set(null);
    this.api
      .replayDlq(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.actionInFlight.set(null);
          this._fetch();
          this.changed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.actionInFlight.set(null);
          this.error.set(extractApiError(err));
        },
      });
  }

  discard(row: IntegrationDLQRow): void {
    if (this.actionInFlight()) return;
    if (row.replayed_at !== null) return;
    if (
      !confirm(
        'Discard this payload? It will stay in the table for audit, but the open-failure counter will exclude it.',
      )
    ) {
      return;
    }
    this.actionInFlight.set(row.id);
    this.error.set(null);
    this.api
      .discardDlq(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.actionInFlight.set(null);
          this._fetch();
          this.changed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.actionInFlight.set(null);
          this.error.set(extractApiError(err));
        },
      });
  }

  // --- view helpers ------------------------------------------------

  /** Discriminator: replayed_at + replayed_by → real replay;
   *  replayed_at + replayed_by=null → discard; both null → open. */
  protected rowStatus(row: IntegrationDLQRow): 'open' | 'replayed' | 'discarded' {
    if (row.replayed_at === null) return 'open';
    if (row.replayed_by === null) return 'discarded';
    return 'replayed';
  }

  protected previewPayload(row: IntegrationDLQRow): string {
    const json = JSON.stringify(row.payload ?? {});
    return json.length > 120 ? json.slice(0, 120) + '…' : json;
  }

  protected formatRelative(iso: string): string {
    const seconds = Math.floor(
      (Date.now() - new Date(iso).getTime()) / 1000,
    );
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  // --- internals ---------------------------------------------------

  private _fetch(): void {
    this.loading.set(true);
    this.error.set(null);
    const filters = {
      page: this.page(),
      size: PAGE_SIZE,
      ...(this.providerFilter()
        ? { provider: this.providerFilter() as IntegrationProvider }
        : {}),
    };
    this.api
      .listDlq(filters)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.rows.set(res.items);
          this.total.set(res.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err));
        },
      });
  }
}

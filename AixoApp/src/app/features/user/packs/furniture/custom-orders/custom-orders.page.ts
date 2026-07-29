import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { ContactsApiService } from '../../../core/contacts/contacts-api.service';
import { ItemMovedEvent, PipelineItem } from '../../../core/pipelines/pipelines-api.service';
import { PipelineBoardComponent } from '../../../core/pipelines/pipeline-board.component';
import { PipelineListComponent } from '../../../core/pipelines/pipeline-list.component';
import { CustomOrderCardComponent } from './custom-order-card.component';
import { CustomOrderFormModalComponent } from './custom-order-form-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import { CustomOrder, CustomOrdersApiService } from './custom-orders-api.service';

/** Stage keys in display order — used for the % progress hint on cards. */
const STAGE_ORDER = [
  'measurement_scheduled',
  'design_phase',
  'in_production',
  'qc',
  'installation',
  'delivered',
];

type View = 'pipeline' | 'list';

interface ContactSummary {
  id: string;
  full_name: string;
  phone: string | null;
}

@Component({
  selector: 'app-custom-orders-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    LucideAngularModule,
    PipelineBoardComponent,
    PipelineListComponent,
    CustomOrderCardComponent,
    CustomOrderFormModalComponent,
  ],
  templateUrl: './custom-orders.page.html',
})
export class CustomOrdersPageComponent {
  private readonly api = inject(CustomOrdersApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly orders = signal<CustomOrder[]>([]);
  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);
  readonly view = signal<View>('pipeline');
  readonly modalOpen = signal(false);
  readonly submitting = signal(false);

  readonly contactsById = signal<Record<string, ContactSummary>>({});

  readonly pipelineItems = computed<PipelineItem[]>(() => this.orders() as PipelineItem[]);

  // --- summary tiles ----------------------------------------------------

  readonly activeCount = computed(
    () =>
      this.orders().filter(
        (o) => o.pipeline_stage !== 'delivered' && o.pipeline_stage !== 'cancelled',
      ).length,
  );

  readonly totalValue = computed(() =>
    this.orders().reduce((sum, o) => sum + Number(o.total_amount ?? 0), 0),
  );

  readonly pendingPayment = computed(() =>
    this.orders().reduce((sum, o) => {
      const total = Number(o.total_amount ?? 0);
      const paid = Number(o.advance_paid ?? 0);
      return sum + Math.max(total - paid, 0);
    }, 0),
  );

  readonly measurementsPending = computed(
    () => this.orders().filter((o) => o.pipeline_stage === 'measurement_scheduled').length,
  );

  constructor() {
    this.reload();

    // Whenever the orders set changes, pull any contact summaries we
    // don't already have cached. Keeps the card component dumb.
    effect(() => {
      const ids = new Set(
        this.orders()
          .map((o) => o.contact_id)
          .filter((id): id is string => id !== null),
      );
      const cache = this.contactsById();
      const missing = [...ids].filter((id) => !cache[id]);
      if (missing.length === 0) return;
      this.fetchContacts(missing);
    });
  }

  protected setView(v: View): void {
    this.view.set(v);
  }

  protected openCreate(): void {
    this.modalOpen.set(true);
  }

  protected closeModal(): void {
    this.modalOpen.set(false);
    this.submitting.set(false);
  }

  protected onCreated(): void {
    this.closeModal();
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({ size: 100 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.orders.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.orders.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load custom orders.');
        },
      });
  }

  protected onItemMoved(event: ItemMovedEvent): void {
    const before = this.orders();
    this.orders.update((rows) =>
      rows.map((r) => (r.id === event.itemId ? { ...r, pipeline_stage: event.toStage } : r)),
    );
    this.api
      .moveStage(event.itemId, event.toStage)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.orders.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
        },
        error: (err: HttpErrorResponse) => {
          this.orders.set(before);
          this.loadError.set(extractApiError(err) ?? 'Could not move order.');
        },
      });
  }

  protected contactFor(id: string | null): ContactSummary | null {
    if (!id) return null;
    return this.contactsById()[id] ?? null;
  }

  protected stageIndexFor(stageKey: string): number | null {
    const idx = STAGE_ORDER.indexOf(stageKey);
    return idx === -1 ? null : idx;
  }

  protected readonly stageTotal = STAGE_ORDER.length;

  protected fmtInr(value: number): string {
    if (value >= 100000) {
      return `₹${(value / 100000).toFixed(1)}L`;
    }
    if (value >= 1000) {
      return `₹${(value / 1000).toFixed(1)}K`;
    }
    return `₹${Math.round(value)}`;
  }

  private fetchContacts(ids: string[]): void {
    forkJoin(ids.map((id) => this.contactsApi.get(id).pipe(catchError(() => of(null)))))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((results) => {
        this.contactsById.update((cache) => {
          const next = { ...cache };
          for (const c of results) {
            if (c) {
              next[c.id] = {
                id: c.id,
                full_name: c.full_name,
                phone: c.phone,
              };
            }
          }
          return next;
        });
      });
  }
}

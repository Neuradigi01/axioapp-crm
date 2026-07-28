import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { catchError, of, switchMap } from 'rxjs';

import { ActivityTimelineComponent } from '../../../core/activities/activity-timeline.component';
import { ContactsApiService } from '../../../core/contacts/contacts-api.service';
import { extractApiError } from '@core/services/api-error.util';
import { deriveApiOrigin } from '@core/services/url.util';
import { fmtInr } from '@core/services/currency.util';
import {
  CustomOrder,
  CustomOrdersApiService,
  Measurement,
  OrderPhoto,
  StageHistoryEntry,
} from './custom-orders-api.service';

/**
 * `/custom-orders/:id` detail view.
 *
 *   - Header: title, contact, stage badge, financial summary.
 *   - Photo gallery (clickable thumbnails open the served URL).
 *   - Measurement table.
 *   - Stage history timeline (this module's append-only ledger).
 *   - Generic `<app-activity-timeline>` for cross-module activity
 *     (status_change events from the pipeline engine, plus any notes
 *     added on the contact).
 */
@Component({
  selector: 'app-custom-order-detail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule, ActivityTimelineComponent],
  templateUrl: './custom-order-detail.page.html',
})
export class CustomOrderDetailPageComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(CustomOrdersApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly order = signal<CustomOrder | null>(null);
  protected readonly measurements = signal<Measurement[]>([]);
  protected readonly photos = signal<OrderPhoto[]>([]);
  protected readonly history = signal<StageHistoryEntry[]>([]);
  protected readonly contactName = signal<string | null>(null);
  protected readonly contactPhone = signal<string | null>(null);
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);

  protected readonly entityType = 'fp_custom_orders';

  /** Absolute base for `/files/...` URLs the backend persists. */
  protected readonly apiOrigin = deriveApiOrigin();

  protected readonly totalInr = computed(() => fmtInr(this.order()?.total_amount));
  protected readonly advanceInr = computed(() => fmtInr(this.order()?.advance_paid));
  protected readonly dueInr = computed(() => {
    const o = this.order();
    if (!o) return '—';
    const due = Math.max(Number(o.total_amount ?? 0) - Number(o.advance_paid ?? 0), 0);
    return fmtInr(String(due));
  });

  protected readonly stageLabel = computed(() => {
    const s = this.order()?.pipeline_stage ?? '';
    return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  });

  protected readonly stageBadgeClass = computed(() => {
    switch (this.order()?.pipeline_stage) {
      case 'measurement_scheduled':
        return 'bg-sky-100 text-sky-700 ring-sky-200';
      case 'design_phase':
        return 'bg-violet-100 text-violet-700 ring-violet-200';
      case 'in_production':
        return 'bg-amber-100 text-amber-700 ring-amber-200';
      case 'qc':
        return 'bg-pink-100 text-pink-700 ring-pink-200';
      case 'installation':
        return 'bg-blue-100 text-blue-700 ring-blue-200';
      case 'delivered':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'cancelled':
        return 'bg-red-100 text-red-700 ring-red-200';
      default:
        return 'bg-surface-2 text-default border-subtle';
    }
  });

  constructor() {
    this.route.paramMap
      .pipe(
        switchMap((params) => {
          const id = params.get('id');
          if (!id) return of(null);
          this.loading.set(true);
          this.loadError.set(null);
          return this.api.get(id).pipe(
            catchError((err: HttpErrorResponse) => {
              this.loadError.set(extractApiError(err) ?? 'Could not load order.');
              this.loading.set(false);
              return of(null);
            }),
          );
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((order) => {
        if (!order) return;
        this.order.set(order);
        this.loading.set(false);
        this.fetchRelated(order);
      });
  }

  protected absoluteUrl(path: string): string {
    if (/^https?:\/\//.test(path)) return path;
    return `${this.apiOrigin}${path}`;
  }

  protected formatDate(iso: string | null | undefined): string {
    if (!iso) return '—';
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return iso;
    return dt.toLocaleDateString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  }

  protected formatDateTime(iso: string): string {
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return iso;
    return dt.toLocaleString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  protected stageLabelFor(key: string | null): string {
    if (!key) return '—';
    return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }

  private fetchRelated(order: CustomOrder): void {
    this.api
      .listMeasurements(order.id)
      .pipe(
        catchError(() => of<Measurement[]>([])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((rows) => this.measurements.set(rows));

    this.api
      .listPhotos(order.id)
      .pipe(
        catchError(() => of<OrderPhoto[]>([])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((rows) => this.photos.set(rows));

    this.api
      .listStageHistory(order.id)
      .pipe(
        catchError(() => of<StageHistoryEntry[]>([])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((rows) => this.history.set(rows));

    if (order.contact_id) {
      this.contactsApi
        .get(order.contact_id)
        .pipe(
          catchError(() => of(null)),
          takeUntilDestroyed(this.destroyRef),
        )
        .subscribe((c) => {
          if (c) {
            this.contactName.set(c.full_name);
            this.contactPhone.set(c.phone);
          }
        });
    }
  }
}

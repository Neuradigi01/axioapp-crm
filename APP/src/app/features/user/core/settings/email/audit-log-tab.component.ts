/**
 * Audit-log tab (tasks/email-inbound-audit-verdicts Step 3).
 *
 * Platform-staff-only surface — the parent tabs list should hide
 * this tab for users who don't hold the required permission. Backend
 * still enforces via ``mailgun.inbound.dlq.manage`` (same key as DLQ
 * admin), so a client-side bypass just returns 403.
 *
 * v1 has no row-detail modal — the audit table only stores metadata,
 * so there's nothing to open into.
 */
import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { format } from 'date-fns';
import { LucideAngularModule } from 'lucide-angular';

import { MobileSelectComponent } from '../../shared/forms/mobile-select.component';
import {
  AuditLogService,
  AuditOutcome,
  InboundDeliveriesListResponse,
  InboundDelivery,
} from './audit-log.service';

const OUTCOME_CHIPS: Array<{ code: AuditOutcome | null; label: string }> = [
  { code: null, label: 'All' },
  { code: 'enqueued', label: 'Enqueued' },
  { code: 'signature_rejected', label: 'Signature rejected' },
  { code: 'replay_rejected', label: 'Replay rejected' },
  { code: 'timestamp_rejected', label: 'Timestamp rejected' },
  { code: 'size_rejected_before_download', label: 'Size rejected' },
];

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
// Same options as ``PAGE_SIZE_OPTIONS`` but shaped for
// ``crm-mobile-select`` (value must be string per its option contract).
const PAGE_SIZE_SELECT_OPTIONS = PAGE_SIZE_OPTIONS.map((n) => ({
  value: String(n),
  label: String(n),
}));

@Component({
  selector: 'app-audit-log-tab',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule, MobileSelectComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './audit-log-tab.component.html',
})
export class AuditLogTabComponent implements OnInit {
  private readonly svc = inject(AuditLogService);

  readonly outcomeChips = OUTCOME_CHIPS;
  readonly pageSizeOptions = PAGE_SIZE_OPTIONS;
  readonly pageSizeSelectOptions = PAGE_SIZE_SELECT_OPTIONS;

  readonly selectedOutcome = signal<AuditOutcome | null>(null);
  readonly fromDate = signal<string>(this.defaultFromDate());
  readonly toDate = signal<string>('');
  readonly page = signal<number>(1);
  readonly pageSize = signal<number>(50);

  readonly rows = signal<InboundDelivery[]>([]);
  readonly total = signal<number>(0);
  readonly loading = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);

  readonly totalPages = computed(() => {
    const total = this.total();
    const size = this.pageSize();
    if (size <= 0) return 1;
    return Math.max(1, Math.ceil(total / size));
  });

  /** ``crm-mobile-select`` needs the value as a string; the component
   *  stores the numeric ``pageSize`` for arithmetic. */
  readonly pageSizeAsString = computed(() => String(this.pageSize()));

  ngOnInit(): void {
    this.load();
  }

  selectOutcome(code: AuditOutcome | null): void {
    if (this.selectedOutcome() === code) return;
    this.selectedOutcome.set(code);
    this.page.set(1);
    this.load();
  }

  changePageSize(size: number): void {
    if (this.pageSize() === size) return;
    this.pageSize.set(size);
    this.page.set(1);
    this.load();
  }

  applyDateFilter(): void {
    this.page.set(1);
    this.load();
  }

  prevPage(): void {
    if (this.page() <= 1) return;
    this.page.update((p) => p - 1);
    this.load();
  }

  nextPage(): void {
    if (this.page() >= this.totalPages()) return;
    this.page.update((p) => p + 1);
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.errorMessage.set(null);
    this.svc
      .list({
        outcome: this.selectedOutcome() ?? undefined,
        from: this.isoOrUndefined(this.fromDate()),
        to: this.isoOrUndefined(this.toDate()),
        page: this.page(),
        page_size: this.pageSize(),
      })
      .subscribe({
        next: (response: InboundDeliveriesListResponse) => {
          this.rows.set(response.items);
          this.total.set(response.total);
          this.loading.set(false);
        },
        error: (err) => {
          this.errorMessage.set(err?.error?.detail ?? 'Failed to load audit log');
          this.loading.set(false);
        },
      });
  }

  outcomeLabel(code: AuditOutcome): string {
    return OUTCOME_CHIPS.find((c) => c.code === code)?.label ?? code;
  }

  formatReceivedAt(iso: string): string {
    return new Date(iso).toLocaleString();
  }

  formatSize(bytes: number | null): string {
    if (bytes == null) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  /** Default window start: 24h ago, as local `YYYY-MM-DDTHH:mm` for the
   *  datetime-local input (which `isoOrUndefined` reads back as local). */
  private defaultFromDate(): string {
    return format(new Date(Date.now() - 24 * 60 * 60 * 1000), "yyyy-MM-dd'T'HH:mm");
  }

  private isoOrUndefined(value: string): string | undefined {
    if (!value) return undefined;
    // ``datetime-local`` inputs return ``YYYY-MM-DDTHH:mm`` with no
    // timezone — treat as browser-local and coerce to UTC ISO.
    const dt = new Date(value);
    if (isNaN(dt.getTime())) return undefined;
    return dt.toISOString();
  }
}

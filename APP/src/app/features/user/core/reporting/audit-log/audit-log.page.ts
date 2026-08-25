import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FeatureAccessService } from '../../billing/services/feature-access.service';
import { LockedFeatureComponent } from '../../billing/components/locked-feature/locked-feature.component';
import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../shared/forms/mobile-select.component';
import { StaffApiService, StaffListItem } from '../../staff/staff-api.service';
import { AuditLogApiService, AuditLogFilters, AuditLogRow } from './audit-log-api.service';

/**
 * Audit log viewer page (Enterprise-only).
 *
 * Recording happens on every plan — the ``audit.log(...)`` calls
 * scattered across the codebase always write into ``tbl_audit_logs``.
 * VIEWING is gated on the ``audit.full_log`` feature flag so that only
 * Enterprise operators see the trail. Lower-plan users hitting this
 * route see the standard "Upgrade to Enterprise" locked-feature card.
 *
 * Layout:
 *   - Filter bar: date range, user, action, entity type
 *   - Paginated table (50 per page): time · user · action · entity · IP
 *   - Row click → side drawer with full details + before/after JSON diff
 *   - Export CSV button (same filters as the visible table)
 */
@Component({
  selector: 'crm-audit-log-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, LucideAngularModule, LockedFeatureComponent, MobileSelectComponent],
  templateUrl: './audit-log.page.html',
})
export class AuditLogPage {
  private readonly api = inject(AuditLogApiService);
  private readonly staffApi = inject(StaffApiService);
  private readonly access = inject(FeatureAccessService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly hasFeature = computed(() => this.access.hasFeature('audit.full_log'));

  // ---- Data + loading state -----------------------------------------
  protected readonly rows = signal<readonly AuditLogRow[]>([]);
  protected readonly total = signal<number>(0);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);

  // ---- Filter state (2-way bound to inputs) -------------------------
  protected readonly actionFilter = signal<string>('');
  protected readonly entityTypeFilter = signal<string>('');
  protected readonly userIdFilter = signal<string>('');
  protected readonly fromFilter = signal<string>('');
  protected readonly toFilter = signal<string>('');
  protected readonly page = signal<number>(1);
  protected readonly size = 50;

  // ---- Drawer (row details) -----------------------------------------
  protected readonly selectedRow = signal<AuditLogRow | null>(null);

  // ---- CSV export state ---------------------------------------------
  protected readonly exporting = signal<boolean>(false);
  protected readonly exportError = signal<string | null>(null);

  // ---- Staff lookup (for the User filter dropdown + row name) -------
  protected readonly staffById = signal<Map<string, StaffListItem>>(new Map());
  protected readonly staffOptions = computed<readonly MobileSelectOption[]>(() => {
    const staff = Array.from(this.staffById().values());
    return [
      { value: '', label: 'All users' },
      ...staff.map((s) => ({ value: s.id, label: s.full_name || s.email || s.id })),
    ];
  });

  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / this.size)));

  constructor() {
    // Only fetch when the plan actually grants the feature — avoids a
    // burst of 402s on every filter change from a Basic user who
    // navigates directly to /user/reports/audit-log.
    if (this.hasFeature()) {
      this.loadStaff();
      this.reload();
    }
  }

  protected reload(): void {
    if (!this.hasFeature()) return;
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list(this._currentFilters())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.rows.set(resp.items);
          this.total.set(resp.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load audit log.');
        },
      });
  }

  protected applyFilters(): void {
    // Any filter change resets pagination to page 1 — matches operator
    // expectation ("I changed my query, show me the first results").
    this.page.set(1);
    this.reload();
  }

  protected clearFilters(): void {
    this.actionFilter.set('');
    this.entityTypeFilter.set('');
    this.userIdFilter.set('');
    this.fromFilter.set('');
    this.toFilter.set('');
    this.applyFilters();
  }

  protected nextPage(): void {
    if (this.page() >= this.totalPages()) return;
    this.page.update((p) => p + 1);
    this.reload();
  }

  protected prevPage(): void {
    if (this.page() <= 1) return;
    this.page.update((p) => p - 1);
    this.reload();
  }

  protected openRow(row: AuditLogRow): void {
    this.selectedRow.set(row);
  }

  protected closeDrawer(): void {
    this.selectedRow.set(null);
  }

  protected async downloadCsv(): Promise<void> {
    if (!this.hasFeature() || this.exporting()) return;
    this.exporting.set(true);
    this.exportError.set(null);
    try {
      await this.api.downloadCsv(this._currentFiltersForExport());
    } catch (err) {
      this.exportError.set(err instanceof Error ? err.message : 'Could not export audit log.');
    } finally {
      this.exporting.set(false);
    }
  }

  protected userDisplayName(userId: string | null): string {
    if (!userId) return 'System';
    const staff = this.staffById().get(userId);
    return staff?.full_name || staff?.email || userId.slice(0, 8);
  }

  protected formatTime(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleString([], {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  }

  protected formatJson(value: unknown): string {
    if (value === null || value === undefined) return '—';
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }

  // ---- Internal helpers ---------------------------------------------

  private loadStaff(): void {
    this.staffApi
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          const map = new Map<string, StaffListItem>();
          for (const s of rows) map.set(s.id, s);
          this.staffById.set(map);
        },
        error: () => {
          // Staff lookup is a nice-to-have for name resolution + the
          // user-filter dropdown; keep the audit log page usable if
          // it fails (rows render with a truncated UUID instead).
          this.staffById.set(new Map());
        },
      });
  }

  private _currentFilters(): AuditLogFilters {
    return {
      action: this.actionFilter().trim() || null,
      entity_type: this.entityTypeFilter().trim() || null,
      user_id: this.userIdFilter() || null,
      from: this.fromFilter() ? new Date(this.fromFilter()).toISOString() : null,
      to: this.toFilter() ? new Date(this.toFilter()).toISOString() : null,
      page: this.page(),
      size: this.size,
    };
  }

  private _currentFiltersForExport(): AuditLogFilters {
    // Export ignores pagination — pull every matching row (up to the
    // backend's 50k safety cap).
    const f = this._currentFilters();
    return { ...f, page: undefined, size: undefined };
  }
}

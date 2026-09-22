/**
 * Quarantine tab (tasks/email-quarantine-filters Step 5).
 *
 * Owner+Admin surface for reviewing held-mail rows.
 * Filter chip by reason_code; row-inline Release / Discard;
 * bulk-release toolbar (only rate_capped rows are eligible per plan).
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
import { LucideAngularModule } from 'lucide-angular';

import { ConfirmDialogService } from '../../shared/confirm-dialog/confirm-dialog.service';
import {
  QuarantineListResponse,
  QuarantineRow,
  QuarantineService,
  ReasonCode,
} from './quarantine.service';

const REASON_CHIPS: Array<{ code: ReasonCode | null; label: string }> = [
  { code: null, label: 'All' },
  { code: 'size_exceeded', label: 'Size' },
  { code: 'blocked_sender', label: 'Blocked' },
  { code: 'rate_capped', label: 'Rate capped' },
  { code: 'spam_verdict', label: 'Spam' },
  { code: 'virus_verdict', label: 'Virus' },
];

@Component({
  selector: 'app-quarantine-tab',
  standalone: true,
  imports: [CommonModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './quarantine-tab.component.html',
})
export class QuarantineTabComponent implements OnInit {
  private readonly svc = inject(QuarantineService);
  private readonly confirmDialog = inject(ConfirmDialogService);

  readonly reasonChips = REASON_CHIPS;
  readonly selectedReason = signal<ReasonCode | null>(null);
  readonly rows = signal<QuarantineRow[]>([]);
  readonly total = signal<number>(0);
  readonly loading = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);
  readonly selectedIds = signal<Set<string>>(new Set());

  /** Bulk-release toolbar only enabled when every selected row is
   * ``rate_capped`` (per plan — other reasons need per-row review). */
  readonly canBulkRelease = computed(() => {
    const ids = this.selectedIds();
    if (ids.size === 0) return false;
    const rows = this.rows();
    for (const id of ids) {
      const row = rows.find((r) => r.id === id);
      if (!row || row.reason_code !== 'rate_capped' || row.status !== 'held') {
        return false;
      }
      if (row.blocked_release) return false;
    }
    return true;
  });

  ngOnInit(): void {
    this.load();
  }

  selectReason(code: ReasonCode | null): void {
    if (this.selectedReason() === code) return;
    this.selectedReason.set(code);
    this.selectedIds.set(new Set());
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.errorMessage.set(null);
    this.svc
      .listQuarantine({
        status: 'held',
        reason_code: this.selectedReason() ?? undefined,
      })
      .subscribe({
        next: (response: QuarantineListResponse) => {
          this.rows.set(response.items);
          this.total.set(response.total);
          this.loading.set(false);
        },
        error: (err) => {
          this.errorMessage.set(err?.error?.detail ?? 'Failed to load quarantine');
          this.loading.set(false);
        },
      });
  }

  toggleSelected(id: string): void {
    const next = new Set(this.selectedIds());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.selectedIds.set(next);
  }

  isSelected(id: string): boolean {
    return this.selectedIds().has(id);
  }

  async release(row: QuarantineRow): Promise<void> {
    if (row.blocked_release) return;
    if (row.reason_code === 'spam_verdict') {
      const ok = await this.confirmDialog.ask({
        title: 'Release this spam-verdict message?',
        body: `Mailgun classified this as spam. Releasing it delivers to the recipient's inbox and publishes the normal workflow events. Confirm it is not spam.`,
        confirmLabel: 'Release',
        cancelLabel: 'Keep held',
        danger: true,
      });
      if (!ok) return;
    }
    this.svc.release(row.id).subscribe({
      next: () => this.load(),
      error: (err) => this.errorMessage.set(err?.error?.detail ?? 'Failed to release message'),
    });
  }

  async discard(row: QuarantineRow): Promise<void> {
    const ok = await this.confirmDialog.ask({
      title: 'Discard this message?',
      body: `The held payload and this quarantine row will be permanently removed. This cannot be undone.`,
      confirmLabel: 'Discard',
      cancelLabel: 'Keep held',
      danger: true,
    });
    if (!ok) return;
    this.svc.discard(row.id).subscribe({
      next: () => this.load(),
      error: (err) => this.errorMessage.set(err?.error?.detail ?? 'Failed to discard message'),
    });
  }

  async bulkRelease(): Promise<void> {
    if (!this.canBulkRelease()) return;
    const ids = Array.from(this.selectedIds());
    const ok = await this.confirmDialog.ask({
      title: `Release ${ids.length} rate-capped message${ids.length === 1 ? '' : 's'}?`,
      body: `Every selected message will be delivered to its recipient as if it had never been rate-capped. Workflow events will publish normally.`,
      confirmLabel: `Release ${ids.length}`,
      cancelLabel: 'Cancel',
    });
    if (!ok) return;
    this.svc.bulkRelease(ids).subscribe({
      next: () => {
        this.selectedIds.set(new Set());
        this.load();
      },
      error: (err) => this.errorMessage.set(err?.error?.detail ?? 'Bulk release failed'),
    });
  }

  formatHeldAt(iso: string): string {
    return new Date(iso).toLocaleString();
  }

  reasonLabel(code: ReasonCode): string {
    const chip = REASON_CHIPS.find((c) => c.code === code);
    return chip?.label ?? code;
  }
}

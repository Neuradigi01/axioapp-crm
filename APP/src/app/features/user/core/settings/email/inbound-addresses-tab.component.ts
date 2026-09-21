/**
 * Inbound Addresses tab (tasks/email-inbound-forwarding Step 5).
 *
 * Owner+Admin-facing list of ``forwarded_address`` endpoints. Each
 * row shows:
 *
 *   * Label + composed forwarding address (with copy button).
 *   * Default assignee (read-only in v1; wizard Step 6 handles
 *     the set-at-create-time flow; row-inline dropdown deferred to a
 *     follow-up polish).
 *   * Auto-create-contact toggle (PATCH inline).
 *   * Last inbound (relative time) + is_active badge.
 *   * Overflow actions: Deactivate (soft) + Delete (hard).
 *
 * Wizard-launch is emitted via ``launchWizard`` output — Step 6
 * lands the actual wizard component under this tab; until then a
 * parent stub can render a simple modal.
 */
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';
import { extractApiError } from '@core/services/api-error.util';

import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { ForwardingWizardComponent } from './forwarding-wizard.component';
import type { ForwardedAddress } from './models';
import { InboundAddressesService } from './inbound-addresses.service';

@Component({
  selector: 'app-inbound-addresses-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ForwardingWizardComponent, LucideAngularModule],
  templateUrl: './inbound-addresses-tab.component.html',
})
export class InboundAddressesTabComponent {
  private readonly api = inject(InboundAddressesService);
  private readonly toast = inject(ToastService);

  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly addresses = signal<ForwardedAddress[]>([]);

  /** Row-id currently in the middle of a PATCH / DELETE — powers the
   * per-row spinner + disables its action buttons. */
  readonly busyId = signal<string | null>(null);

  /** True while the Step-6 wizard modal is mounted. */
  readonly showWizard = signal(false);

  readonly sortedAddresses = computed<ReadonlyArray<ForwardedAddress>>(() => {
    const rows = this.addresses();
    const active = rows.filter((r) => r.is_active);
    const inactive = rows.filter((r) => !r.is_active);
    return [...active, ...inactive];
  });

  constructor() {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.list().subscribe({
      next: (rows) => {
        this.addresses.set(rows);
        this.loading.set(false);
      },
      error: (err) => {
        this.loadError.set(extractApiError(err) ?? 'Could not load inbound addresses.');
        this.loading.set(false);
      },
    });
  }

  /** Mount the Step-6 3-step forwarding wizard. */
  launchWizard(): void {
    this.showWizard.set(true);
  }

  /** Wizard emitted ``close`` (either after "Received!", after the
   * 5min timeout, or via explicit close). Refresh the list so a
   * freshly-created endpoint appears. */
  onWizardClose(): void {
    this.showWizard.set(false);
    this.reload();
  }

  async copyAddress(row: ForwardedAddress): Promise<void> {
    if (!row.forwarding_address) return;
    await navigator.clipboard.writeText(row.forwarding_address);
    this.toast.success(`Copied ${row.forwarding_address}`);
  }

  toggleAutoCreate(row: ForwardedAddress): void {
    this.busyId.set(row.id);
    const next = !row.auto_create_contact;
    this.api.update(row.id, { auto_create_contact: next }).subscribe({
      next: (updated) => {
        this._replaceRow(updated);
        this.busyId.set(null);
      },
      error: (err) => {
        this.busyId.set(null);
        this.toast.error(extractApiError(err) ?? 'Update failed.');
      },
    });
  }

  deactivate(row: ForwardedAddress): void {
    const confirmed = window.confirm(
      `Deactivate ${row.label}? Mail arriving at ${row.forwarding_address} will stop reaching the CRM. ` +
        `You can reactivate this address later without losing the token.`,
    );
    if (!confirmed) return;
    this.busyId.set(row.id);
    this.api.deactivate(row.id).subscribe({
      next: () => {
        this.busyId.set(null);
        this.toast.success(`${row.label} deactivated.`);
        this.reload();
      },
      error: (err) => {
        this.busyId.set(null);
        this.toast.error(extractApiError(err) ?? 'Deactivation failed.');
      },
    });
  }

  remove(row: ForwardedAddress): void {
    const confirmed = window.confirm(
      `Delete ${row.label}? Any mail arriving at ${row.forwarding_address} after deletion won't reach the CRM. ` +
        `Historical messages on the conversation stay intact. This cannot be undone.`,
    );
    if (!confirmed) return;
    this.busyId.set(row.id);
    this.api.remove(row.id).subscribe({
      next: () => {
        this.busyId.set(null);
        this.toast.success(`${row.label} deleted.`);
        this.reload();
      },
      error: (err) => {
        this.busyId.set(null);
        this.toast.error(extractApiError(err) ?? 'Delete failed.');
      },
    });
  }

  /** Relative "5 min ago" formatting. Matches the SendingDomainsTab
   * formatter; centralising the helper is a follow-up polish. */
  lastInboundLabel(iso: string | null): string {
    if (!iso) return 'No mail yet';
    const then = new Date(iso).getTime();
    const delta = Math.max(0, Date.now() - then);
    const mins = Math.floor(delta / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  private _replaceRow(updated: ForwardedAddress): void {
    this.addresses.update((current) => current.map((r) => (r.id === updated.id ? updated : r)));
  }
}

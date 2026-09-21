/**
 * Sending Domains tab (tasks/email-sending-domains Step 7).
 *
 * Owner-only surface for the Mailgun-managed sending-domains flow.
 * Rendered inside Settings when the caller holds
 * ``email.sending_domains.manage`` (parent tab list filters visibility).
 *
 * States rendered:
 *
 *   * empty — "No sending domains claimed" + CTA
 *   * pending — grey badge + copy-paste DNS records + "Check now"
 *   * verified — green badge + "Last verified <relative>"
 *   * demoted — amber warning banner (memory
 *     ``feedback_standard_warning_banner_pattern``) + "Check now"
 *   * released — grey badge with strikethrough (historical record)
 *
 * Claim / verify / release fire the shipped backend endpoints — see
 * :class:`SendingDomainsService`. This component is a dumb renderer
 * over ``dns_records`` (Mailgun's verbatim shape) — any provider-side
 * schema drift lands as one narrow DAL change, no UI rewrite.
 */
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';
import { extractApiError } from '@core/services/api-error.util';

import { DnsRecordCardComponent } from '../../shared/dns/dns-record-card.component';
import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { ClaimDomainModalComponent } from './claim-domain-modal.component';
import type { ClaimDomainRequest, SendingDomain } from './models';
import { SendingDomainsService } from './sending-domains.service';

@Component({
  selector: 'app-sending-domains-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ClaimDomainModalComponent, DnsRecordCardComponent, LucideAngularModule],
  templateUrl: './sending-domains-tab.component.html',
})
export class SendingDomainsTabComponent {
  private readonly api = inject(SendingDomainsService);
  private readonly toast = inject(ToastService);

  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly domains = signal<SendingDomain[]>([]);
  readonly expandedId = signal<string | null>(null);

  readonly showClaimModal = signal(false);
  readonly claiming = signal(false);

  /** In-flight verify/release per row-id → button spinner. */
  readonly busyId = signal<string | null>(null);

  /** Non-released rows first (newest at top), released rows at the
   * bottom of the list so the historical timeline stays visible
   * without cluttering the active view. */
  readonly sortedDomains = computed<ReadonlyArray<SendingDomain>>(() => {
    const rows = this.domains();
    const active = rows.filter((r) => r.verification_status !== 'released');
    const released = rows.filter((r) => r.verification_status === 'released');
    return [...active, ...released];
  });

  constructor() {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.list().subscribe({
      next: (rows) => {
        this.domains.set(rows);
        this.loading.set(false);
      },
      error: (err) => {
        this.loadError.set(extractApiError(err) ?? 'Could not load sending domains.');
        this.loading.set(false);
      },
    });
  }

  toggleExpanded(id: string): void {
    this.expandedId.update((current) => (current === id ? null : id));
  }

  openClaim(): void {
    this.showClaimModal.set(true);
  }

  cancelClaim(): void {
    if (this.claiming()) return;
    this.showClaimModal.set(false);
  }

  submitClaim(payload: ClaimDomainRequest): void {
    this.claiming.set(true);
    this.api.claim(payload).subscribe({
      next: (row) => {
        // Insert-at-top so the operator sees the fresh DNS records
        // immediately — parity with the empty-state → first-row flow.
        this.domains.update((current) => [row, ...current]);
        this.expandedId.set(row.id);
        this.showClaimModal.set(false);
        this.claiming.set(false);
        this.toast.success(`Claimed ${row.domain}. Publish the DNS records below to verify.`);
      },
      error: (err) => {
        this.claiming.set(false);
        this.toast.error(extractApiError(err) ?? 'Could not claim domain.');
      },
    });
  }

  verify(row: SendingDomain): void {
    this.busyId.set(row.id);
    this.api.verify(row.id).subscribe({
      next: (updated) => {
        this._replaceRow(updated);
        this.busyId.set(null);
        if (updated.verification_status === 'verified') {
          this.toast.success(`${updated.domain} verified. Sends can now go out from this domain.`);
        } else {
          this.toast.info(
            `${updated.domain} not verified yet. Check that every DNS record is published.`,
          );
        }
      },
      error: (err) => {
        this.busyId.set(null);
        this.toast.error(extractApiError(err) ?? 'Verification failed.');
      },
    });
  }

  release(row: SendingDomain): void {
    const confirmed = window.confirm(
      `Release ${row.domain}? Sends will fall back to the platform sending domain until you re-claim.`,
    );
    if (!confirmed) return;
    this.busyId.set(row.id);
    this.api.release(row.id).subscribe({
      next: () => {
        // Backend flips to ``released`` — refresh via list so the row
        // reflects the new state (and stays visible in the timeline).
        this.busyId.set(null);
        this.toast.success(`${row.domain} released.`);
        this.reload();
      },
      error: (err) => {
        this.busyId.set(null);
        this.toast.error(extractApiError(err) ?? 'Could not release domain.');
      },
    });
  }

  onRecordCopied(): void {
    this.toast.success('Copied to clipboard.');
  }

  /** Badge colour + label per verification_status. */
  statusBadgeClass(status: SendingDomain['verification_status']): string {
    switch (status) {
      case 'verified':
        return 'bg-emerald-500/15 text-emerald-500 border border-emerald-500/20';
      case 'pending':
        return 'bg-zinc-400/15 text-zinc-400 border border-zinc-400/20';
      case 'demoted':
        return 'bg-amber-500/15 text-amber-400 border border-amber-500/20';
      case 'released':
        return 'bg-zinc-500/15 text-zinc-500 border border-zinc-500/20 line-through';
    }
  }

  statusLabel(status: SendingDomain['verification_status']): string {
    switch (status) {
      case 'verified':
        return 'Verified';
      case 'pending':
        return 'Pending verification';
      case 'demoted':
        return 'DNS drift detected';
      case 'released':
        return 'Released';
    }
  }

  /** Relative "5 min ago" formatting for ``last_verified_at``. Returns
   * empty string when null so the template can hide the whole line. */
  lastVerifiedLabel(isoString: string | null): string {
    if (!isoString) return '';
    const then = new Date(isoString).getTime();
    const nowMs = Date.now();
    const delta = Math.max(0, nowMs - then);
    const mins = Math.floor(delta / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  private _replaceRow(updated: SendingDomain): void {
    this.domains.update((current) => current.map((r) => (r.id === updated.id ? updated : r)));
  }
}

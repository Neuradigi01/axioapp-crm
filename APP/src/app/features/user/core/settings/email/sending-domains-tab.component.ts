/**
 * Sending Domains tab (tasks/email-sending-domains Step 7).
 *
 * Owner-only surface for the Mailgun-managed sending-domains flow.
 * Rendered inside Settings → Integrations → Email → Sending domains
 * when the caller holds ``email.sending_domains.manage`` (parent tab
 * list filters visibility).
 *
 * UI shape follows Prativani's reference:
 *   * The claim form is **inline** at the top of the tab, not a modal.
 *   * No Region selector — Mailgun's region is set at the account level
 *     via the ``MAILGUN_REGION`` env, so per-org exposure was noise.
 *     The tab always sends ``region: 'us'`` (backend default); ops
 *     override at the env layer if EU is needed.
 *   * Each domain row has a 3-dot overflow menu (Release lives there).
 *   * Expanded-records footer offers "Copy all as a zone file" and
 *     "Send to whoever manages DNS" (mailto link) helpers.
 */
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { extractApiError } from '@core/services/api-error.util';

import { ConfirmDialogService } from '../../shared/confirm-dialog/confirm-dialog.service';
import { DnsRecordCardComponent } from '../../shared/dns/dns-record-card.component';
import { commonValidators } from '../../shared/validators';
import { ToastService } from '../../../../../shared/components/toast/toast.service';
import type { ClaimDomainRequest, DnsRecord, SendingDomain } from './models';
import { SendingDomainsService } from './sending-domains.service';

@Component({
  selector: 'app-sending-domains-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DnsRecordCardComponent, LucideAngularModule, ReactiveFormsModule],
  templateUrl: './sending-domains-tab.component.html',
})
export class SendingDomainsTabComponent {
  private readonly api = inject(SendingDomainsService);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder);
  private readonly confirmDialog = inject(ConfirmDialogService);
  private readonly host = inject(ElementRef<HTMLElement>);

  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly domains = signal<SendingDomain[]>([]);
  readonly expandedId = signal<string | null>(null);

  readonly claiming = signal(false);
  /** The inline claim card is shown by default so an operator can
   *  claim immediately without hunting for a button. Matches Prativani's
   *  flow — the form is always one click away, never a modal. */
  readonly claimFormOpen = signal(true);

  /** In-flight verify/release per row-id → button spinner. */
  readonly busyId = signal<string | null>(null);

  /** Which row's 3-dot overflow menu is open (id → menu shown). */
  readonly openMenuId = signal<string | null>(null);

  /** Inline claim form. Region deliberately absent — see class docstring. */
  protected readonly claimForm = {
    domain: this.fb.control<string>('', {
      nonNullable: true,
      validators: [
        Validators.required,
        Validators.minLength(3),
        Validators.maxLength(253),
        commonValidators.hostnameApex,
      ],
    }) as FormControl<string>,
  };

  /** Non-released rows first (newest at top), released rows at the
   *  bottom of the list so the historical timeline stays visible
   *  without cluttering the active view. */
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

  toggleClaimForm(): void {
    this.claimFormOpen.update((v) => !v);
    if (this.claimFormOpen()) this.claimForm.domain.reset('');
  }

  cancelClaim(): void {
    if (this.claiming()) return;
    this.claimForm.domain.reset('');
    // Leave the form open so the operator can immediately re-try;
    // Prativani keeps the card mounted after cancel.
  }

  submitClaim(): void {
    if (this.claiming()) return;
    if (this.claimForm.domain.invalid) {
      this.claimForm.domain.markAsTouched();
      return;
    }
    const domain = (this.claimForm.domain.value || '').trim().toLowerCase().replace(/\.+$/, '');
    // Region is always ``'us'`` at the UI layer. Ops override via
    // ``MAILGUN_REGION`` env at the backend if EU is needed.
    const payload: ClaimDomainRequest = { domain, region: 'us' };
    this.claiming.set(true);
    this.api.claim(payload).subscribe({
      next: (row) => {
        this.domains.update((current) => [row, ...current]);
        this.expandedId.set(row.id);
        this.claimForm.domain.reset('');
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

  async release(row: SendingDomain): Promise<void> {
    this.openMenuId.set(null);
    const ok = await this.confirmDialog.ask({
      title: `Release ${row.domain}?`,
      body: `Sends will fall back to the platform sending domain until you re-claim. Existing DNS records at your provider stay untouched.`,
      confirmLabel: 'Release',
      cancelLabel: 'Keep it',
      danger: true,
    });
    if (!ok) return;
    this.busyId.set(row.id);
    this.api.release(row.id).subscribe({
      next: () => {
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

  toggleOverflowMenu(id: string): void {
    this.openMenuId.update((current) => (current === id ? null : id));
  }

  /** Close the overflow menu when the user clicks anywhere outside it. */
  @HostListener('document:mousedown', ['$event.target'])
  onDocumentClick(target: EventTarget | null): void {
    if (!this.openMenuId()) return;
    if (!(target instanceof Node)) {
      this.openMenuId.set(null);
      return;
    }
    if (!this.host.nativeElement.contains(target)) {
      this.openMenuId.set(null);
    }
  }

  onRecordCopied(): void {
    this.toast.success('Copied to clipboard.');
  }

  /** Compose a BIND-style zone-file fragment from the row's DNS records
   *  and copy it to the clipboard. */
  copyZoneFile(row: SendingDomain): void {
    const all: DnsRecord[] = [...row.dns_records.sending, ...row.dns_records.receiving];
    const lines = all.map((r) => this._toZoneLine(r)).filter((l): l is string => l !== null);
    const text = lines.join('\n') + '\n';
    void navigator.clipboard.writeText(text).then(
      () => this.toast.success('Zone file copied to clipboard.'),
      () => this.toast.error('Could not copy zone file.'),
    );
  }

  /** Compose a ``mailto:`` URL pre-filled with the zone file so the
   *  operator can email whoever manages their DNS in one click. */
  buildMailtoLink(row: SendingDomain): string {
    const all: DnsRecord[] = [...row.dns_records.sending, ...row.dns_records.receiving];
    const zoneBody = all
      .map((r) => this._toZoneLine(r))
      .filter((l): l is string => l !== null)
      .join('\n');
    const subject = `DNS records for ${row.domain}`;
    const body = [
      `Hi,`,
      ``,
      `Please add these DNS records to ${row.domain} so we can send verified email from it:`,
      ``,
      zoneBody,
      ``,
      `Thanks!`,
    ].join('\n');
    return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  }

  private _toZoneLine(r: DnsRecord): string | null {
    if (!r.name || !r.value || !r.record_type) return null;
    const type = r.record_type.toUpperCase();
    const host = r.name.endsWith('.') ? r.name : `${r.name}.`;
    if (type === 'MX') {
      const target = r.value.endsWith('.') ? r.value : `${r.value}.`;
      const prio = r.priority ?? '10';
      return `${host} IN MX ${prio} ${target}`;
    }
    if (type === 'TXT') {
      const escaped = r.value.replace(/"/g, '\\"');
      return `${host} IN TXT "${escaped}"`;
    }
    if (type === 'CNAME') {
      const target = r.value.endsWith('.') ? r.value : `${r.value}.`;
      return `${host} IN CNAME ${target}`;
    }
    return `${host} IN ${type} ${r.value}`;
  }

  statusBadgeClass(status: SendingDomain['verification_status']): string {
    switch (status) {
      case 'verified':
        return 'bg-emerald-500/15 text-emerald-500 border border-emerald-500/20';
      case 'pending':
        return 'bg-amber-500/15 text-amber-400 border border-amber-500/20';
      case 'demoted':
        return 'bg-red-500/15 text-red-400 border border-red-500/20';
      case 'released':
        return 'bg-zinc-500/15 text-zinc-500 border border-zinc-500/20 line-through';
    }
  }

  statusLabel(status: SendingDomain['verification_status']): string {
    switch (status) {
      case 'verified':
        return 'Verified';
      case 'pending':
        return 'DNS pending';
      case 'demoted':
        return 'DNS drift';
      case 'released':
        return 'Released';
    }
  }

  /** "No addresses yet · Checked 2m ago" — Prativani-style subline
   *  under the domain name. */
  checkedLabel(row: SendingDomain): string {
    const rel = row.last_verified_at ? this._relativeLabel(row.last_verified_at) : null;
    if (rel) return `Checked ${rel}`;
    return 'Not checked yet';
  }

  private _relativeLabel(isoString: string): string {
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

/**
 * Settings → Sender Setup tab (Campaigns v1 Step 07b).
 *
 * Owner + Admin only (gated by ``email.accounts.admin`` — see the tab
 * def in ``settings-page.component.ts``). Users register the domain(s)
 * they'll send email campaigns from, publish the DNS records the modal
 * hands them, and click Verify to have the backend re-check SPF / DKIM
 * / DMARC against public DNS.
 *
 * State machine per row:
 *
 *   pending  (no verifications yet)
 *   partial  (SPF or DMARC present but DKIM absent, or vice versa)
 *   verified (all three green)
 *
 * The verify endpoint is rate-limited to once per minute per (org,
 * domain) — a 429 surfaces here as an inline tooltip so the operator
 * knows to wait instead of hammering.
 */
import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  EmailSenderDnsRecord,
  EmailSenderDomain,
  EmailSenderSetupApiService,
} from '../../services/email-sender-setup-api.service';
import { AddDomainModalComponent } from './add-domain-modal.component';
import { DnsRecordsModalComponent } from './dns-records-modal.component';

type Tone = 'success' | 'error';

@Component({
  selector: 'app-sender-setup-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, LucideAngularModule, AddDomainModalComponent, DnsRecordsModalComponent],
  templateUrl: './sender-setup-tab.component.html',
})
export class SenderSetupTabComponent implements OnInit {
  private readonly api = inject(EmailSenderSetupApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly domains = signal<EmailSenderDomain[] | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly inlineError = signal<string | null>(null);
  protected readonly toast = signal<{ tone: Tone; message: string } | null>(null);

  protected readonly addModalOpen = signal(false);
  protected readonly creating = signal(false);

  /** DNS-records modal state — populated by clicking "View DNS records". */
  protected readonly dnsModal = signal<{
    domain: string;
    records: EmailSenderDnsRecord[];
  } | null>(null);
  protected readonly dnsLoadingId = signal<string | null>(null);

  /** Row-level in-flight state for the Verify button so multiple rows
   *  can be independently rate-limited without freezing the table. */
  protected readonly verifyingId = signal<string | null>(null);
  protected readonly deletingId = signal<string | null>(null);

  protected readonly verifiedCount = computed(
    () => this.domains()?.filter((d) => this._isFullyVerified(d)).length ?? 0,
  );

  protected readonly emptyState = computed(() => (this.domains()?.length ?? 0) === 0);

  ngOnInit(): void {
    this._load();
  }

  // --- actions ------------------------------------------------

  refresh(): void {
    this._load();
  }

  openAdd(): void {
    this.inlineError.set(null);
    this.addModalOpen.set(true);
  }

  closeAdd(): void {
    if (this.creating()) return;
    this.addModalOpen.set(false);
  }

  submitAdd(domain: string): void {
    if (this.creating()) return;
    this.creating.set(true);
    this.api
      .createDomain(domain)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.creating.set(false);
          this.addModalOpen.set(false);
          this.toast.set({
            tone: 'success',
            message: `Added ${row.domain}. Publish the DNS records, then click Verify.`,
          });
          this._load();
          // Auto-open the DNS records modal so the operator can copy
          // the records without an extra click.
          this._loadDns(row.id);
        },
        error: (err: HttpErrorResponse) => {
          this.creating.set(false);
          this.inlineError.set(extractApiError(err) ?? 'Could not add domain.');
        },
      });
  }

  openDns(row: EmailSenderDomain): void {
    this._loadDns(row.id);
  }

  closeDns(): void {
    this.dnsModal.set(null);
  }

  verify(row: EmailSenderDomain): void {
    if (this.verifyingId() !== null) return;
    this.verifyingId.set(row.id);
    this.inlineError.set(null);
    this.api
      .verifyDomain(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.verifyingId.set(null);
          this.toast.set({
            tone: result.fully_verified ? 'success' : 'error',
            message: result.fully_verified
              ? `${result.domain} — SPF, DKIM, DMARC all verified.`
              : `${result.domain} — ${this._explainPartial(result)}`,
          });
          this._load();
        },
        error: (err: HttpErrorResponse) => {
          this.verifyingId.set(null);
          if (err.status === 429) {
            this.inlineError.set(
              'Verification refreshes are limited to once per minute per domain. Try again shortly.',
            );
          } else {
            this.inlineError.set(extractApiError(err) ?? 'Could not verify domain.');
          }
        },
      });
  }

  remove(row: EmailSenderDomain): void {
    const confirmed = window.confirm(
      `Remove ${row.domain} from the sender registry? Existing mailboxes on this domain will keep working, but they'll show as un-verified in the campaign wizard.`,
    );
    if (!confirmed) return;
    this.deletingId.set(row.id);
    this.inlineError.set(null);
    this.api
      .deleteDomain(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deletingId.set(null);
          this.toast.set({ tone: 'success', message: `Removed ${row.domain}.` });
          this._load();
        },
        error: (err: HttpErrorResponse) => {
          this.deletingId.set(null);
          this.inlineError.set(extractApiError(err) ?? 'Could not remove domain.');
        },
      });
  }

  dismissToast(): void {
    this.toast.set(null);
  }

  // --- render helpers -----------------------------------------

  protected badgeClass(state: 'green' | 'amber' | 'zinc'): string {
    if (state === 'green') return 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200';
    if (state === 'amber') return 'bg-amber-50 text-amber-700 ring-1 ring-amber-200';
    return 'bg-zinc-100 text-zinc-600 ring-1 ring-zinc-200';
  }

  protected checkState(verified: boolean, lastChecked: string | null): 'green' | 'amber' | 'zinc' {
    if (verified) return 'green';
    if (lastChecked) return 'amber';
    return 'zinc';
  }

  protected checkLabel(verified: boolean, lastChecked: string | null): string {
    if (verified) return 'Verified';
    if (lastChecked) return 'Failing';
    return 'Pending';
  }

  protected rowStatus(row: EmailSenderDomain): {
    label: string;
    tone: 'green' | 'amber' | 'zinc';
  } {
    if (this._isFullyVerified(row)) return { label: 'Verified', tone: 'green' };
    if (row.spf_verified || row.dkim_verified || row.dmarc_verified) {
      return { label: 'Partial', tone: 'amber' };
    }
    return { label: 'Pending', tone: 'zinc' };
  }

  // --- internals ----------------------------------------------

  private _isFullyVerified(row: EmailSenderDomain): boolean {
    return row.spf_verified && row.dkim_verified && row.dmarc_verified;
  }

  private _explainPartial(v: {
    spf_verified: boolean;
    dkim_verified: boolean;
    dmarc_verified: boolean;
  }): string {
    const missing: string[] = [];
    if (!v.spf_verified) missing.push('SPF');
    if (!v.dkim_verified) missing.push('DKIM');
    if (!v.dmarc_verified) missing.push('DMARC');
    return missing.length === 0
      ? 'all checks passed.'
      : `${missing.join(', ')} not yet detected — check the DNS records.`;
  }

  private _load(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listDomains()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.domains.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load domains.');
        },
      });
  }

  private _loadDns(domainId: string): void {
    this.dnsLoadingId.set(domainId);
    this.api
      .dnsRecords(domainId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.dnsLoadingId.set(null);
          this.dnsModal.set({ domain: res.domain, records: res.records });
        },
        error: (err: HttpErrorResponse) => {
          this.dnsLoadingId.set(null);
          this.inlineError.set(extractApiError(err) ?? 'Could not load DNS records.');
        },
      });
  }
}

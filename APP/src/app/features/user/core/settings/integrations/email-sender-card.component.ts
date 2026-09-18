/**
 * Email-sender card on the Integrations page.
 *
 * Renders alongside Google Ads / Meta / WhatsApp cards. Shows the
 * org's unified sender list (verified SMTP senders + live OAuth
 * mailboxes) and — once ≥1 SMTP sender exists — a Domain
 * Authentication sub-section that reuses the existing
 * `add-domain-modal` + `dns-records-modal` from `sender-setup/`.
 *
 * Owner-managed via the `email.accounts.manage` permission (backend
 * enforces; the card only surfaces when the caller can see the
 * endpoint).
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { ConfirmDialogComponent } from '../../shared/confirm-dialog/confirm-dialog.component';
import { AddDomainModalComponent } from '../sender-setup/add-domain-modal.component';
import { DnsRecordsModalComponent } from '../sender-setup/dns-records-modal.component';
import {
  EmailSenderDnsRecord,
  EmailSenderDomain,
  EmailSenderSetupApiService,
} from '../../services/email-sender-setup-api.service';
import { AddSenderIdentityModalComponent } from './add-sender-identity-modal.component';
import { EmailAccountsApiService } from '../../services/email-accounts-api.service';
import {
  EmailSendersApiService,
  SmtpSender,
  UnifiedSender,
  UnifiedSenderKind,
} from './email-senders-api.service';
import { VerifySenderCodeModalComponent } from './verify-sender-code-modal.component';

type Toast = { tone: 'success' | 'error'; message: string };

@Component({
  selector: 'app-email-sender-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DatePipe,
    LucideAngularModule,
    AddSenderIdentityModalComponent,
    VerifySenderCodeModalComponent,
    AddDomainModalComponent,
    DnsRecordsModalComponent,
    ConfirmDialogComponent,
  ],
  templateUrl: './email-sender-card.component.html',
})
export class EmailSenderCardComponent implements OnInit {
  private readonly api = inject(EmailSendersApiService);
  private readonly accountsApi = inject(EmailAccountsApiService);
  private readonly domainsApi = inject(EmailSenderSetupApiService);
  private readonly destroyRef = inject(DestroyRef);
  /** Zoneless-mode belt-and-braces: HTTP subscribe callbacks land
   *  signal writes but the view sometimes doesn't repaint until the
   *  next user interaction. Explicit `markForCheck()` after every
   *  async mutation removes the race — same pattern as the fix in
   *  `lead-follow-ups-panel.component.ts`. */
  private readonly cdr = inject(ChangeDetectorRef);

  protected readonly senders = signal<UnifiedSender[] | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly rowError = signal<string | null>(null);
  protected readonly toast = signal<Toast | null>(null);

  protected readonly addModalOpen = signal(false);
  protected readonly verifyModal = signal<{ id: string; from: string } | null>(null);

  /** Pending destructive-action confirm. Replaces the three previous
   *  `window.confirm` calls (delete SMTP sender / disconnect OAuth
   *  mailbox / remove domain) with the shared `<app-confirm-dialog>`
   *  so the messaging and button styling match the rest of the UI
   *  instead of showing an OS-native browser prompt. `action` is the
   *  closure that fires the actual API call — captured with its row
   *  argument at trigger time. `null` means no dialog open. */
  protected readonly pendingConfirm = signal<{
    title: string;
    body: string;
    confirmLabel: string;
    action: () => void;
  } | null>(null);

  protected readonly settingDefaultId = signal<string | null>(null);
  protected readonly deletingId = signal<string | null>(null);

  /** Row-level busy flags for the OAuth Gmail / Microsoft actions.
   *  Prevent double-click on Reconnect (which redirects) and on
   *  Disconnect (soft-delete). */
  protected readonly reconnectingId = signal<string | null>(null);
  protected readonly disconnectingId = signal<string | null>(null);

  /** mailgun-inbound track: which SMTP row is currently flipping its
   *  capture toggle. Prevents double-click while the PATCH is in
   *  flight; row-level so multiple senders can flip concurrently. */
  protected readonly togglingCaptureId = signal<string | null>(null);
  /** mailgun-inbound track: which SMTP row just had its reply
   *  address copied to the clipboard. Used to swap the Copy icon
   *  → Check for 1.5s, matching the DNS-records-modal pattern. */
  protected readonly copiedReplyId = signal<string | null>(null);

  // --- Domain-authentication sub-section state (reused SPF/DKIM/DMARC UI).
  protected readonly domains = signal<EmailSenderDomain[] | null>(null);
  protected readonly domainsLoading = signal(false);
  protected readonly domainsError = signal<string | null>(null);
  protected readonly addDomainOpen = signal(false);
  protected readonly creatingDomain = signal(false);
  protected readonly verifyingDomainId = signal<string | null>(null);
  protected readonly deletingDomainId = signal<string | null>(null);
  protected readonly dnsModal = signal<{
    domain: string;
    records: EmailSenderDnsRecord[];
  } | null>(null);

  protected readonly hasSmtpSender = computed(() =>
    (this.senders() ?? []).some((s) => s.kind === 'smtp'),
  );

  protected readonly emptyState = computed(() => (this.senders()?.length ?? 0) === 0);

  ngOnInit(): void {
    this._load();
  }

  // --- sender-list actions ------------------------------------

  openAdd(): void {
    this.rowError.set(null);
    this.addModalOpen.set(true);
  }

  closeAdd(): void {
    this.addModalOpen.set(false);
  }

  onSmtpCreated(payload: { sender: SmtpSender; from: string }): void {
    this.addModalOpen.set(false);
    this.verifyModal.set({ id: payload.sender.id, from: payload.from });
    this._load();
  }

  closeVerify(): void {
    this.verifyModal.set(null);
  }

  onVerified(sender: SmtpSender): void {
    this.verifyModal.set(null);
    this.toast.set({
      tone: 'success',
      message: `${sender.from_address} verified. It's now available as an outbound sender.`,
    });
    this._load();
    if (!this.hasSmtpSender()) {
      // Optimistic — the create just went through so we can eagerly
      // load domains on the assumption that at least one row is
      // present. `_load()` runs concurrently and will settle the
      // authoritative state.
      this._loadDomains();
    } else {
      this._loadDomains();
    }
  }

  setDefault(row: UnifiedSender): void {
    // Any verified/connected sender can be the default — SMTP, Gmail,
    // or Microsoft. `row.verified` doubles as the sendability gate:
    // SMTP → verified_at is set; OAuth → refresh_token present AND
    // sync_state != disconnected (see list_unified_senders).
    if (row.is_default || !row.verified) return;
    this.settingDefaultId.set(row.id);
    this.rowError.set(null);
    this.api
      .setDefault(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.settingDefaultId.set(null);
          this.toast.set({
            tone: 'success',
            message: `Default sender set to ${row.from_address}.`,
          });
          this._load();
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.settingDefaultId.set(null);
          this.rowError.set(extractApiError(err) ?? 'Could not set default sender.');
          this.cdr.markForCheck();
        },
      });
  }

  remove(row: UnifiedSender): void {
    if (row.kind !== 'smtp') return;
    this.pendingConfirm.set({
      title: `Delete SMTP sender ${row.from_address}?`,
      body: 'Automations and workflows that send email will fall back to another verified sender (if any) or skip until you add one back.',
      confirmLabel: 'Delete',
      action: () => this._doRemove(row),
    });
  }

  private _doRemove(row: UnifiedSender): void {
    this.deletingId.set(row.id);
    this.rowError.set(null);
    this.api
      .delete(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deletingId.set(null);
          this.toast.set({ tone: 'success', message: `Removed ${row.from_address}.` });
          this._load();
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.deletingId.set(null);
          this.rowError.set(extractApiError(err) ?? 'Could not delete sender.');
          this.cdr.markForCheck();
        },
      });
  }

  resendVerification(row: UnifiedSender): void {
    if (row.kind !== 'smtp' || row.verified) return;
    this.verifyModal.set({ id: row.id, from: row.from_address });
  }

  /** Re-run Google / Microsoft OAuth for a Gmail / Microsoft row.
   *  Reuses the same authorize URL as first-time connect — the
   *  callback upserts the existing `email_accounts` row keyed on
   *  `(provider, email_address)`, so this replaces the dead refresh
   *  token with a fresh one without touching sender-identity state.
   *  Redirect is a full-page navigation, so no unmount cleanup. */
  reconnect(row: UnifiedSender): void {
    if (row.kind !== 'gmail' && row.kind !== 'microsoft') return;
    if (this.reconnectingId() !== null) return;
    this.reconnectingId.set(row.id);
    this.rowError.set(null);
    const req$ =
      row.kind === 'gmail'
        ? this.accountsApi.authorizeGmail()
        : this.accountsApi.authorizeMicrosoft();
    req$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: ({ url }) => {
        window.location.assign(url);
      },
      error: (err: HttpErrorResponse) => {
        this.reconnectingId.set(null);
        this.rowError.set(extractApiError(err) ?? 'Could not start reconnect.');
        this.cdr.markForCheck();
      },
    });
  }

  /** Soft-disconnect a Gmail / Microsoft mailbox. Nulls the stored
   *  tokens + flips `sync_state` to `disconnected`; the row is kept
   *  so history survives. Inbox replies from this mailbox stop
   *  working until the operator reconnects. */
  disconnect(row: UnifiedSender): void {
    if (row.kind !== 'gmail' && row.kind !== 'microsoft') return;
    if (this.disconnectingId() !== null) return;
    this.pendingConfirm.set({
      title: `Disconnect ${row.from_address}?`,
      body: 'Inbox email replies from this mailbox will stop working until you reconnect it. Historical messages are kept.',
      confirmLabel: 'Disconnect',
      action: () => this._doDisconnect(row),
    });
  }

  private _doDisconnect(row: UnifiedSender): void {
    this.disconnectingId.set(row.id);
    this.rowError.set(null);
    this.accountsApi
      .disconnect(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.disconnectingId.set(null);
          this.toast.set({ tone: 'success', message: `Disconnected ${row.from_address}.` });
          this._load();
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.disconnectingId.set(null);
          this.rowError.set(extractApiError(err) ?? 'Could not disconnect account.');
          this.cdr.markForCheck();
        },
      });
  }

  dismissToast(): void {
    this.toast.set(null);
  }

  // --- mailgun-inbound Reply capture actions -----------------

  /** Copy this sender's `in_<token>@…` reply address to the clipboard.
   *  Swallows the Permissions API rejection some browsers surface —
   *  the failure toast pattern already exists for other copy flows
   *  in `dns-records-modal`; here the intent is a passive success
   *  indicator, so silence on failure is preferable to noise. */
  async copyReplyAddress(row: UnifiedSender): Promise<void> {
    const address = row.inbound_reply_address?.address;
    if (!address) return;
    try {
      await navigator.clipboard.writeText(address);
      this.copiedReplyId.set(row.id);
      setTimeout(() => {
        if (this.copiedReplyId() === row.id) {
          this.copiedReplyId.set(null);
          this.cdr.markForCheck();
        }
      }, 1500);
      this.cdr.markForCheck();
    } catch {
      // Permission-denied / no clipboard — fall through silently.
    }
  }

  /** mailgun-inbound track: flip `capture_replies_in_crm` on the
   *  server + reflect the new state locally on success. Optimistic
   *  updates rolled back on error so the toggle mirrors the server.
   *  Failure surfaces via the existing row-level `rowError` banner. */
  toggleCapture(row: UnifiedSender, next: boolean): void {
    if (row.kind !== 'smtp') return;
    if (!row.inbound_reply_address) return;
    if (this.togglingCaptureId() !== null) return;

    this.togglingCaptureId.set(row.id);
    this.rowError.set(null);
    this.api
      .setCaptureToggle(row.id, next)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.togglingCaptureId.set(null);
          // Merge the server response into the local list — avoids
          // a full refetch just to flip one boolean.
          this.senders.update((rows) => {
            if (!rows) return rows;
            return rows.map((r) =>
              r.id === row.id
                ? {
                    ...r,
                    inbound_reply_address: updated.inbound_reply_address ?? null,
                  }
                : r,
            );
          });
          this.toast.set({
            tone: 'success',
            message: next
              ? `Replies to ${row.from_address} now land in the CRM.`
              : `Replies to ${row.from_address} will go to your SMTP mailbox.`,
          });
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.togglingCaptureId.set(null);
          this.rowError.set(extractApiError(err) ?? 'Could not update reply capture.');
          this.cdr.markForCheck();
        },
      });
  }

  // --- Domain authentication actions --------------------------

  openAddDomain(): void {
    this.domainsError.set(null);
    this.addDomainOpen.set(true);
  }

  closeAddDomain(): void {
    if (this.creatingDomain()) return;
    this.addDomainOpen.set(false);
  }

  submitDomain(domain: string): void {
    if (this.creatingDomain()) return;
    this.creatingDomain.set(true);
    this.domainsApi
      .createDomain(domain)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.creatingDomain.set(false);
          this.addDomainOpen.set(false);
          this.toast.set({
            tone: 'success',
            message: `Added ${row.domain}. Publish the DNS records, then click Verify.`,
          });
          this._loadDomains();
          this._loadDnsForDomain(row.id);
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.creatingDomain.set(false);
          this.domainsError.set(extractApiError(err) ?? 'Could not add domain.');
          this.cdr.markForCheck();
        },
      });
  }

  verifyDomain(row: EmailSenderDomain): void {
    if (this.verifyingDomainId() !== null) return;
    this.verifyingDomainId.set(row.id);
    this.domainsError.set(null);
    this.domainsApi
      .verifyDomain(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.verifyingDomainId.set(null);
          this.toast.set({
            tone: result.fully_verified ? 'success' : 'error',
            message: result.fully_verified
              ? `${result.domain} — SPF, DKIM, DMARC all verified.`
              : `${result.domain} — DNS records not yet detected. Try again in a few minutes.`,
          });
          this._loadDomains();
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.verifyingDomainId.set(null);
          if (err.status === 429) {
            this.domainsError.set(
              'Verification refreshes are limited to once per minute per domain.',
            );
          } else {
            this.domainsError.set(extractApiError(err) ?? 'Could not verify domain.');
          }
          this.cdr.markForCheck();
        },
      });
  }

  showDns(row: EmailSenderDomain): void {
    this._loadDnsForDomain(row.id);
  }

  closeDns(): void {
    this.dnsModal.set(null);
  }

  removeDomain(row: EmailSenderDomain): void {
    this.pendingConfirm.set({
      title: `Remove ${row.domain} from the sender registry?`,
      body: "Existing mailboxes on this domain will keep working, but they'll show as un-verified in the campaign wizard.",
      confirmLabel: 'Remove',
      action: () => this._doRemoveDomain(row),
    });
  }

  private _doRemoveDomain(row: EmailSenderDomain): void {
    this.deletingDomainId.set(row.id);
    this.domainsError.set(null);
    this.domainsApi
      .deleteDomain(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deletingDomainId.set(null);
          this.toast.set({ tone: 'success', message: `Removed ${row.domain}.` });
          this._loadDomains();
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.deletingDomainId.set(null);
          this.domainsError.set(extractApiError(err) ?? 'Could not remove domain.');
          this.cdr.markForCheck();
        },
      });
  }

  /** Runs the pending action + closes the dialog. Wired from the
   *  shared confirm-dialog `(confirm)` output. */
  protected onConfirmPending(): void {
    const p = this.pendingConfirm();
    if (!p) return;
    this.pendingConfirm.set(null);
    p.action();
  }

  /** Dismisses the dialog without running the action. Wired from the
   *  shared confirm-dialog `(cancel)` output. */
  protected onCancelPending(): void {
    this.pendingConfirm.set(null);
  }

  // --- render helpers -----------------------------------------

  protected providerLabel(kind: UnifiedSenderKind): string {
    return kind === 'gmail' ? 'Gmail' : kind === 'microsoft' ? 'Microsoft' : 'SMTP';
  }

  protected providerBadgeClasses(kind: UnifiedSenderKind): string {
    if (kind === 'gmail') return 'bg-blue-50 text-blue-700 ring-1 ring-blue-200';
    if (kind === 'microsoft') return 'bg-sky-50 text-sky-700 ring-1 ring-sky-200';
    return 'bg-surface-2 text-default ring-1 border-subtle';
  }

  /** True iff this OAuth sender's grant is dead — Google/Microsoft
   *  rejected the refresh token, so the next send will 401. The
   *  card renders a red "Reconnect needed" pill + the raw error
   *  when this is true, instead of the misleading green "Connected"
   *  pill that used to hide the problem until send failed. */
  protected isOauthRevoked(row: UnifiedSender): boolean {
    if (row.kind === 'smtp') return false;
    if (row.sync_state === 'error') return true;
    const err = (row.last_sync_error ?? '').toLowerCase();
    if (!err) return false;
    return (
      err.includes('invalid_grant') ||
      err.includes('revoked') ||
      err.includes('unauthorized') ||
      err.includes('token has been expired')
    );
  }

  /** Human "10 min" / "2 hr" / "1 day" formatted time until the
   *  short-lived access token expires. `null` on SMTP or when the
   *  backend didn't populate the field. Google refreshes silently
   *  on healthy grants so this label just reassures the operator
   *  that the session is live; if it stops advancing, the row will
   *  also flip to "Reconnect needed" via `isOauthRevoked`. */
  protected tokenExpiryLabel(row: UnifiedSender): string | null {
    if (row.kind === 'smtp') return null;
    if (!row.token_expires_at) return null;
    const t = new Date(row.token_expires_at).getTime();
    if (isNaN(t)) return null;
    const mins = Math.round((t - Date.now()) / 60_000);
    if (mins <= 0) return 'expired';
    if (mins < 60) return `${mins} min`;
    const hours = Math.round(mins / 60);
    if (hours < 48) return `${hours} hr`;
    const days = Math.round(hours / 24);
    return `${days} day${days === 1 ? '' : 's'}`;
  }

  protected domainState(row: EmailSenderDomain): {
    label: string;
    tone: 'green' | 'amber' | 'zinc';
  } {
    if (row.spf_verified && row.dkim_verified && row.dmarc_verified) {
      return { label: 'Verified', tone: 'green' };
    }
    if (row.spf_verified || row.dkim_verified || row.dmarc_verified) {
      return { label: 'Partial', tone: 'amber' };
    }
    return { label: 'Pending', tone: 'zinc' };
  }

  protected domainToneClass(tone: 'green' | 'amber' | 'zinc'): string {
    if (tone === 'green') return 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200';
    if (tone === 'amber') return 'bg-amber-50 text-amber-700 ring-1 ring-amber-200';
    return 'bg-surface-2 text-muted ring-1 border-subtle';
  }

  // --- internals ----------------------------------------------

  private _load(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.senders.set(rows);
          this.loading.set(false);
          if (this.hasSmtpSender()) {
            this._loadDomains();
          } else {
            this.domains.set(null);
          }
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load senders.');
          this.cdr.markForCheck();
        },
      });
  }

  private _loadDomains(): void {
    this.domainsLoading.set(true);
    this.domainsApi
      .listDomains()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.domains.set(rows);
          this.domainsLoading.set(false);
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.domainsLoading.set(false);
          this.domainsError.set(extractApiError(err) ?? 'Could not load domains.');
          this.cdr.markForCheck();
        },
      });
  }

  private _loadDnsForDomain(domainId: string): void {
    this.domainsApi
      .dnsRecords(domainId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.dnsModal.set({ domain: res.domain, records: res.records });
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.domainsError.set(extractApiError(err) ?? 'Could not load DNS records.');
          this.cdr.markForCheck();
        },
      });
  }
}

/**
 * Settings → Email Accounts tab.
 *
 * Lists the caller's connected mailboxes (Owners + Admins with the
 * `email.accounts.admin` scope see every account in the org via the
 * same call — the backend decides what the list contains).
 *
 * Per-row UI:
 *   - provider badge (Gmail / Microsoft)
 *   - email address + display name
 *   - sync-state pill (pending / backfilling / live / error / disconnected)
 *   - last-sync timestamp (relative-formatted; falls back to "never")
 *   - daily send count vs hard cap (default 500/day per account)
 *   - last-error tooltip when state=error
 *   - Disconnect button (rep can only disconnect own; admin can
 *     disconnect any — backend enforces)
 *
 * Auto-refresh: while any visible row is in `pending` or `backfilling`
 * we poll `list()` every 30s so the operator sees the transition to
 * `live` without manually reloading. The poll halts as soon as every
 * row is in a terminal-ish state (live / error / disconnected).
 *
 * Status-toast hook: when the page lands via `?status=connected`
 * (the OAuth callback's redirect target), we show a success toast
 * once and strip the param. `?status=denied` / `?status=error` show
 * matching error toasts.
 */
import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { EmailAccount, EmailAccountsApiService } from '../../services/email-accounts-api.service';
import { ConnectAccountCardComponent } from './connect-account-card.component';
import { DisconnectConfirmDialogComponent } from './disconnect-confirm-dialog.component';
import { DomainStatusComponent } from './domain-status.component';
import { SuppressionListComponent } from './suppression-list.component';

/** Hard cap matches the backend `DEFAULT_HARD_CAP` constant in
 *  `core/email/gmail/send.py` + `core/email/microsoft/send.py`.
 *  Keep these in sync — overshooting the floor breaks the UI gauge. */
const DAILY_HARD_CAP = 500;

/** Soft cap — backend logs a warning at this threshold. We render
 *  the gauge in amber once the live count crosses it. */
const DAILY_SOFT_CAP = 200;

const REFRESH_MS = 30_000;

const TRANSIENT_STATES = new Set<EmailAccount['sync_state']>(['pending', 'backfilling']);

@Component({
  selector: 'app-email-accounts-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DatePipe,
    LucideAngularModule,
    ConnectAccountCardComponent,
    DisconnectConfirmDialogComponent,
    DomainStatusComponent,
    SuppressionListComponent,
  ],
  templateUrl: './email-accounts-tab.component.html',
})
export class EmailAccountsTabComponent implements OnInit, OnDestroy {
  private readonly api = inject(EmailAccountsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly accounts = signal<EmailAccount[] | null>(null);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly inlineError = signal<string | null>(null);

  protected readonly toast = signal<{
    tone: 'success' | 'error';
    message: string;
  } | null>(null);

  protected readonly disconnectTarget = signal<EmailAccount | null>(null);
  protected readonly disconnecting = signal<boolean>(false);

  private _refreshTimer: ReturnType<typeof setInterval> | null = null;

  /** Visible-rows-needing-poll → drives the auto-refresh loop. */
  protected readonly hasTransientRows = computed(() => {
    const rows = this.accounts();
    if (!rows) return false;
    return rows.some((r) => TRANSIENT_STATES.has(r.sync_state));
  });

  protected readonly emptyState = computed(() => (this.accounts()?.length ?? 0) === 0);

  protected readonly cap = DAILY_HARD_CAP;
  protected readonly softCap = DAILY_SOFT_CAP;

  ngOnInit(): void {
    this._readStatusQueryParam();
    this._load();
  }

  ngOnDestroy(): void {
    this._stopPolling();
  }

  // --- actions --------------------------------------------------

  refresh(): void {
    this._load();
  }

  openDisconnect(account: EmailAccount): void {
    this.inlineError.set(null);
    this.disconnectTarget.set(account);
  }

  cancelDisconnect(): void {
    if (this.disconnecting()) return;
    this.disconnectTarget.set(null);
  }

  confirmDisconnect(): void {
    const target = this.disconnectTarget();
    if (!target || this.disconnecting()) return;
    this.disconnecting.set(true);
    this.api
      .disconnect(target.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.disconnecting.set(false);
          this.disconnectTarget.set(null);
          this.toast.set({
            tone: 'success',
            message: `Disconnected ${target.email_address}.`,
          });
          this._load();
        },
        error: (err: HttpErrorResponse) => {
          this.disconnecting.set(false);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  onConnectError(message: string): void {
    this.inlineError.set(message);
  }

  dismissToast(): void {
    this.toast.set(null);
  }

  // --- helpers --------------------------------------------------

  protected readonly stateLabel: Record<EmailAccount['sync_state'], string> = {
    pending: 'Pending',
    backfilling: 'Backfilling',
    live: 'Live',
    error: 'Error',
    disconnected: 'Disconnected',
  };

  protected readonly statePillClasses: Record<EmailAccount['sync_state'], string> = {
    pending: 'bg-zinc-100 text-zinc-700 ring-1 ring-zinc-200',
    backfilling: 'bg-blue-50 text-blue-700 ring-1 ring-blue-200 animate-pulse',
    live: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',
    error: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200',
    disconnected: 'bg-zinc-100 text-zinc-600 ring-1 ring-zinc-200',
  };

  sentCountTone(row: EmailAccount): string {
    if (row.daily_sent_count >= DAILY_HARD_CAP) return 'text-rose-600';
    if (row.daily_sent_count >= DAILY_SOFT_CAP) return 'text-amber-600';
    return 'text-zinc-700';
  }

  // --- internals ------------------------------------------------

  private _load(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.accounts.set(rows);
          this.loading.set(false);
          this._reconcilePolling();
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err));
          this._stopPolling();
        },
      });
  }

  /** Start polling when any row is transient; stop otherwise. */
  private _reconcilePolling(): void {
    if (this.hasTransientRows()) {
      this._startPolling();
    } else {
      this._stopPolling();
    }
  }

  private _startPolling(): void {
    if (this._refreshTimer !== null) return;
    this._refreshTimer = setInterval(() => {
      // Don't stack a refresh on top of an in-flight one.
      if (this.loading()) return;
      this._load();
    }, REFRESH_MS);
  }

  private _stopPolling(): void {
    if (this._refreshTimer !== null) {
      clearInterval(this._refreshTimer);
      this._refreshTimer = null;
    }
  }

  /** Reads `?status=` from the OAuth callback and shows a one-shot
   *  toast, then strips the param so a back/forward navigation
   *  doesn't re-trigger it. */
  private _readStatusQueryParam(): void {
    const qp = this.route.snapshot.queryParamMap;
    const status = qp.get('status');
    if (!status) return;
    if (status === 'connected') {
      this.toast.set({
        tone: 'success',
        message:
          'Mailbox connected. Sync is starting — it can take a minute for the first batch to appear.',
      });
    } else if (status === 'gmail_denied' || status === 'microsoft_denied') {
      this.toast.set({
        tone: 'error',
        message: 'OAuth consent was declined. The mailbox is not connected.',
      });
    } else if (status.endsWith('_error') || status === 'error') {
      this.toast.set({
        tone: 'error',
        message: qp.get('reason')
          ? `Connection failed: ${qp.get('reason')}`
          : 'Connection failed. Please try again.',
      });
    }
    // Strip the status params from the URL.
    this.router.navigate([], {
      queryParams: {
        status: null,
        reason: null,
        account: null,
      },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }
}

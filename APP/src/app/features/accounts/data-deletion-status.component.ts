/**
 * Public status page for Meta's Data Deletion Callback
 * (whatsapp-platform-upgrade Step 4).
 *
 * Anonymous reader — no auth, no chrome. The URL Meta hands the user
 * after they delete our app from their Facebook profile looks like:
 *
 *   https://app.core-crm.com/data-deletion-status?confirmation_code=<token>
 *
 * Meta itself periodically re-fetches the same URL (sometimes months
 * later) to confirm the user can still see the deletion status. The
 * route must stay valid forever, so the row in
 * `tbl_meta_data_deletion_requests` is never deleted on the backend.
 *
 * The component polls the backend every 3 seconds while the status is
 * `pending` or `in_progress` and stops once it lands on `completed`
 * or `failed`. A separate "demo" path (`?confirmation_code=demo-test-
 * 12345`) is provided for the Meta App Review screencast — backend
 * returns a synthetic completed projection without touching the DB.
 *
 * Lives under `features/accounts/` per the step spec, but registered
 * as a top-level public route in `app.routes.ts` (peer of `/pricing`)
 * so it doesn't inherit the accounts login chrome.
 */
import { CommonModule, DatePipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
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
import { ActivatedRoute } from '@angular/router';

import { environment } from '../../../environments/environment';


type DeletionStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | 'failed'
  | 'unknown';


interface StatusResponse {
  status: DeletionStatus;
  confirmation_code: string;
  requested_at: string;
  completed_at: string | null;
  affected_org_count: number;
  is_demo: boolean;
}


// Polling cadence chosen to match Meta's typical user expectation
// (status feedback within a few seconds). Anything faster wastes
// backend cycles on a slow-changing async job.
const POLL_INTERVAL_MS = 3_000;


@Component({
  selector: 'app-data-deletion-status',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, DatePipe],
  templateUrl: './data-deletion-status.component.html',
})
export class DataDeletionStatusComponent implements OnInit, OnDestroy {
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly response = signal<StatusResponse | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly loading = signal(true);

  protected readonly confirmationCode = signal<string | null>(null);

  protected readonly displayStatus = computed<DeletionStatus>(() => {
    const r = this.response();
    return r ? r.status : 'unknown';
  });

  private pollHandle: ReturnType<typeof setTimeout> | null = null;

  ngOnInit(): void {
    const code = this.route.snapshot.queryParamMap.get('confirmation_code');
    if (!code) {
      this.error.set(
        'Missing confirmation_code. The link in your privacy settings ' +
          'may be incomplete — please re-open it from Facebook.',
      );
      this.loading.set(false);
      return;
    }
    this.confirmationCode.set(code);
    this.pollOnce();
  }

  ngOnDestroy(): void {
    if (this.pollHandle !== null) {
      clearTimeout(this.pollHandle);
      this.pollHandle = null;
    }
  }

  private pollOnce(): void {
    const code = this.confirmationCode();
    if (!code) return;
    this.http
      .get<StatusResponse>(
        `${environment.apiBaseUrl}/integrations/meta/data-deletion/status`,
        { params: { confirmation_code: code } },
      )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.response.set(res);
          this.loading.set(false);
          // Schedule the next poll only while there's progress to
          // observe — terminal states stop the cycle to keep the page
          // idle.
          if (res.status === 'pending' || res.status === 'in_progress') {
            this.pollHandle = setTimeout(
              () => this.pollOnce(),
              POLL_INTERVAL_MS,
            );
          }
        },
        error: (err) => {
          this.loading.set(false);
          if (err && err.status === 404) {
            this.error.set(
              'No deletion request matches that link. The link may have ' +
                'expired or been copied incorrectly.',
            );
          } else {
            this.error.set(
              'Unable to load deletion status. Please try again in a moment.',
            );
          }
        },
      });
  }
}

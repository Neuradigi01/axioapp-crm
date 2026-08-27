import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { EMPTY, catchError, of, switchMap } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { ToastService } from '../../../../shared/components/toast/toast.service';

/**
 * Redirects legacy `/user/automations/:id` bookmarks to the equivalent
 * `/user/workflows/:workflow_id` after the workflows-absorb-automation
 * cutover (Step 3 of `tasks/workflows-absorb-automation/`).
 *
 * The Step-1 data migration populated `tbl_automation_triggers.migrated_to_workflow_id`
 * for every existing automation. This component reads that FK via a
 * lightweight endpoint (`GET /api/v1/automations/triggers/:id/migrated-workflow-id`)
 * and navigates to the matched workflow's canvas. If the endpoint 404s
 * / errors / returns `{workflow_id: null}` the user falls back to
 * `/user/workflows` (the list).
 *
 * A one-time toast surfaces the URL change so operators don't wonder
 * why they landed on Workflows — the `automation-redirect-seen` flag
 * in `localStorage` gates subsequent visits so the toast doesn't
 * repeat.
 */
@Component({
  selector: 'app-redirect-automation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex min-h-[60vh] items-center justify-center text-sm text-zinc-500">
      Redirecting to Workflows…
    </div>
  `,
})
export class RedirectAutomationComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);

  private static readonly TOAST_STORAGE_KEY = 'automation-redirect-seen';
  private static readonly TOAST_TITLE = 'Automations are now Workflows';
  private static readonly TOAST_SUBTITLE = 'Redirected to the Workflows page.';

  ngOnInit(): void {
    const triggerId = this.route.snapshot.paramMap.get('id');
    this.showToastOnce();

    if (!triggerId) {
      // No id in the URL (e.g. /user/automations) — bounce to the
      // list page.
      void this.router.navigate(['/user/workflows']);
      return;
    }

    this.http
      .get<{ workflow_id: string | null }>(
        `${environment.apiBaseUrl}/automations/triggers/${triggerId}/migrated-workflow-id`,
      )
      .pipe(
        switchMap((resp) => {
          if (resp?.workflow_id) {
            return this.router.navigate(['/user/workflows', resp.workflow_id]);
          }
          return this.router.navigate(['/user/workflows']);
        }),
        catchError((err: HttpErrorResponse) => {
          // 403 / 404 / network — graceful fallback to the list. The
          // toast has already fired so the user still sees the URL
          // change explanation.
          console.warn(
            '[redirect-automation] resolver failed, falling back to workflows list',
            err?.status ?? err,
          );
          void this.router.navigate(['/user/workflows']);
          return of(EMPTY);
        }),
      )
      .subscribe();
  }

  private showToastOnce(): void {
    try {
      if (localStorage.getItem(RedirectAutomationComponent.TOAST_STORAGE_KEY)) {
        return;
      }
      this.toast.info(RedirectAutomationComponent.TOAST_TITLE, {
        subtitle: RedirectAutomationComponent.TOAST_SUBTITLE,
        durationMs: 5000,
      });
      localStorage.setItem(RedirectAutomationComponent.TOAST_STORAGE_KEY, '1');
    } catch {
      // localStorage unavailable (private mode / SSR) — silently skip.
    }
  }
}

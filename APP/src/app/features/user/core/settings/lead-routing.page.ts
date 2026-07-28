import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { RouterLink } from '@angular/router';

import { extractApiError } from '@core/services/api-error.util';
import { LeadRoutingStrategy, LeadsApiService } from '../leads/leads-api.service';

/**
 * Settings → Lead Routing (E.16 / F1).
 *
 * Owner + Admin can pick which routing strategy the ingest pipeline
 * uses when it assigns a new lead. v1 offers only ``round_robin`` —
 * the schema Literal on the backend rejects anything else, so the
 * dropdown intentionally has a single option today. Future strategies
 * (``sticky_by_source``, geo-based, workload-balanced) slot in as
 * additional options without an API break.
 *
 * Not much interactivity right now, but the page is where users go
 * to *understand* how their leads are being distributed — the copy
 * explains that eligible users are those with the ``leads.own``
 * permission on their role, and points at the Roles page for that
 * setup.
 */
@Component({
  selector: 'app-lead-routing-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, LucideAngularModule, RouterLink],
  template: `
    <div class="mx-auto max-w-3xl space-y-5 p-6">
      <header>
        <h1 class="text-lg font-semibold text-default">Lead routing</h1>
        <p class="mt-0.5 text-xs text-muted">
          How new leads are assigned to reps when they land — from manual entry, the embed widget,
          ad integrations, or bulk imports.
        </p>
      </header>

      @if (loadError(); as err) {
        <p class="rounded-md bg-red-50 px-4 py-2 text-xs text-red-700 ring-1 ring-red-200">
          {{ err }}
        </p>
      }

      @if (saved()) {
        <p
          class="rounded-md bg-emerald-50 px-4 py-2 text-xs text-emerald-700 ring-1 ring-emerald-200"
        >
          Routing strategy saved.
        </p>
      }

      <section class="rounded-lg bg-surface p-5 shadow-sm ring-1 border-subtle">
        <h2 class="text-sm font-semibold text-default">Assignment strategy</h2>
        <p class="mt-1 text-xs text-muted">
          Picks the rep for each freshly-ingested lead. Applies to every ingest path (manual,
          widget, Google Ads, Meta Ads, bulk import).
        </p>

        <label class="mt-3 block">
          <span class="text-xs font-medium text-default">Strategy</span>
          <select
            [ngModel]="strategy()"
            (ngModelChange)="strategy.set($event)"
            [disabled]="loading() || submitting()"
            class="mt-1 block w-full max-w-xs rounded-md border border-subtle bg-surface px-3 py-2 text-sm text-default shadow-sm focus:border-muted focus:outline-none focus:ring-1 focus:ring-accent"
          >
            <option value="round_robin">Round-robin (rotate through eligible reps)</option>
          </select>
        </label>

        <p class="mt-3 text-xs text-muted">
          <strong class="text-default">Eligible reps</strong> are users whose role holds the
          <code class="rounded bg-surface-2 px-1 py-0.5 font-mono">leads.own</code> permission.
          Grant or revoke that permission on the
          <a
            routerLink="/user/settings"
            [queryParams]="{ tab: 'roles' }"
            class="text-default underline hover:text-default"
            >Roles page</a
          >. If no user in your org holds it, new leads land unassigned and show under the
          "Unassigned" filter on the kanban.
        </p>

        <div class="mt-5 flex justify-end">
          <button
            type="button"
            (click)="onSave()"
            [disabled]="loading() || submitting()"
            class="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-2 text-sm font-medium text-white hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
          >
            @if (submitting()) {
              <lucide-icon name="loader-2" class="h-3.5 w-3.5 animate-spin" />
              Saving…
            } @else {
              Save
            }
          </button>
        </div>
      </section>

      <section class="rounded-lg bg-surface p-5 shadow-sm ring-1 border-subtle">
        <h2 class="text-sm font-semibold text-default">Related settings</h2>
        <ul class="mt-2 space-y-1 text-xs text-muted">
          <li>
            <a
              routerLink="/user/settings/lead-scoring"
              class="inline-flex items-center gap-1 text-default underline hover:text-default"
            >
              <lucide-icon name="target" class="h-3.5 w-3.5" />
              Lead scoring rules
            </a>
            &mdash; automatic score based on lead-field conditions.
          </li>
          <li>
            <a
              routerLink="/user/settings"
              [queryParams]="{ tab: 'roles' }"
              class="inline-flex items-center gap-1 text-default underline hover:text-default"
            >
              <lucide-icon name="users" class="h-3.5 w-3.5" />
              Roles &amp; permissions
            </a>
            &mdash; grant <code class="rounded bg-surface-2 px-1 py-0.5 font-mono">leads.own</code>
            to reps who should receive assignments.
          </li>
        </ul>
      </section>
    </div>
  `,
})
export class LeadRoutingPage {
  private readonly api = inject(LeadsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly strategy = signal<LeadRoutingStrategy>('round_robin');
  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly submitting = signal(false);
  readonly saved = signal(false);

  constructor() {
    this.reload();
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .getRoutingConfig()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (cfg) => {
          this.strategy.set(cfg.strategy);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load routing config.');
        },
      });
  }

  protected onSave(): void {
    this.submitting.set(true);
    this.saved.set(false);
    this.loadError.set(null);
    this.api
      .updateRoutingConfig({ strategy: this.strategy() })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (cfg) => {
          this.strategy.set(cfg.strategy);
          this.submitting.set(false);
          this.saved.set(true);
          // Auto-clear the "Saved" banner after a moment so it doesn't
          // sit forever after the user moved on.
          setTimeout(() => this.saved.set(false), 2500);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not save routing config.');
        },
      });
  }
}

/**
 * Per-assistant analytics page
 * (``tasks/ai-assistants`` Step 16).
 *
 * Two KPI cards + a top-questions list, scoped to a single assistant
 * over a rolling window. Matches the workflow-analytics visual
 * pattern (grid of ``bg-surface rounded-lg border`` cards + a
 * simple table below).
 *
 * v1 shows a 30-day window only; a preset switcher (7/30/90) can be
 * bolted on when operators ask for it.
 */
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';
import { switchMap } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';
import { AiAssistantAnalyticsResponse, AiAssistantsApiService } from '../ai-assistants-api.service';

@Component({
  selector: 'app-ai-assistant-analytics-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule, RouterLink],
  templateUrl: './analytics.page.html',
})
export class AiAssistantAnalyticsPage {
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(AiAssistantsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly assistantId = signal<string | null>(null);
  protected readonly data = signal<AiAssistantAnalyticsResponse | null>(null);
  protected readonly windowDays = signal(30);

  /** Convenience: cost formatted for display. Keeps template compact
   *  and avoids repeating the toFixed(4) rounding everywhere. */
  protected readonly costUsdDisplay = computed(() => {
    const d = this.data();
    if (d === null) return '$0.00';
    // Cost comes back as a string (Decimal) so precision survives
    // JSON. Format to 4 dp — a single chat typically bills sub-cent.
    const raw = Number(d.total_cost_usd);
    if (!Number.isFinite(raw)) return '$0.00';
    return `$${raw.toFixed(4)}`;
  });

  protected readonly hasTopQuestions = computed(
    () => (this.data()?.top_questions?.length ?? 0) > 0,
  );

  constructor() {
    this.route.paramMap
      .pipe(
        switchMap((params) => {
          const id = params.get('id');
          this.loading.set(true);
          this.error.set(null);
          this.data.set(null);
          if (!id) {
            this.error.set('Missing assistant id.');
            this.loading.set(false);
            return [];
          }
          this.assistantId.set(id);
          return this.api.getAnalytics(id, this.windowDays());
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => {
          this.data.set(resp);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load analytics.');
        },
      });
  }
}

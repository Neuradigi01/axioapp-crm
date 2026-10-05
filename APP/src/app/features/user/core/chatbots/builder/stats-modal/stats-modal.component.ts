import { CommonModule, PercentPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { ChatbotStats, ChatbotsApiService } from '../../chatbots-api.service';
import { nodeTypeLabel } from '../node-type-registry';

/**
 * Bot analytics modal — aggregates run counts by status, completion
 * rate, and the top 5 executed nodes. Reads on open, no polling.
 * Numbers exclude ``is_test`` runs so the view reflects real
 * customer activity.
 */
@Component({
  selector: 'app-chatbot-stats-modal',
  standalone: true,
  imports: [CommonModule, PercentPipe, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      (click)="close.emit()"
    >
      <div
        class="bg-surface border border-subtle rounded-xl w-[540px] max-w-[92vw] max-h-[85vh] flex flex-col shadow-2xl"
        (click)="$event.stopPropagation()"
      >
        <header class="flex items-center gap-3 px-5 py-4 border-b border-subtle">
          <span
            class="w-8 h-8 rounded-lg bg-accent-soft text-accent inline-flex items-center justify-center"
          >
            <lucide-icon name="bar-chart-3" size="16"></lucide-icon>
          </span>
          <div class="flex-1">
            <h2 class="text-sm font-semibold text-default">Bot analytics</h2>
            <p class="text-[11px] text-muted mt-0.5">
              Real customer runs only (test runs are excluded).
            </p>
          </div>
          <button
            type="button"
            (click)="close.emit()"
            class="p-1.5 rounded hover:bg-surface-2 text-muted hover:text-default"
            aria-label="Close"
          >
            <lucide-icon name="x" size="16"></lucide-icon>
          </button>
        </header>

        <div class="flex-1 overflow-y-auto p-5">
          @if (loading()) {
            <div class="flex items-center justify-center py-10 text-sm text-muted">
              <lucide-icon name="loader-2" size="14" class="animate-spin mr-2"></lucide-icon>
              Loading stats…
            </div>
          } @else if (error()) {
            <div class="text-sm text-red-500">{{ error() }}</div>
          } @else if (stats(); as s) {
            @if (s.total_runs === 0) {
              <div class="py-10 text-center text-sm text-muted">
                No runs yet. Send a matching inbound message to your bot to see stats here.
              </div>
            } @else {
              <div class="grid grid-cols-3 gap-3 mb-5">
                <div class="p-3 rounded-lg bg-app border border-subtle">
                  <div class="text-[10px] font-semibold text-muted uppercase tracking-wider">
                    Total runs
                  </div>
                  <div class="text-2xl font-bold text-default mt-1">{{ s.total_runs }}</div>
                </div>
                <div class="p-3 rounded-lg bg-app border border-subtle">
                  <div class="text-[10px] font-semibold text-muted uppercase tracking-wider">
                    Completion rate
                  </div>
                  <div class="text-2xl font-bold text-emerald-500 mt-1">
                    {{ s.completion_rate | percent: '1.0-1' }}
                  </div>
                </div>
                <div class="p-3 rounded-lg bg-app border border-subtle">
                  <div class="text-[10px] font-semibold text-muted uppercase tracking-wider">
                    In progress
                  </div>
                  <div class="text-2xl font-bold text-accent mt-1">
                    {{ s.running + s.parked }}
                  </div>
                </div>
              </div>

              <h3 class="text-[11px] font-semibold text-muted uppercase tracking-wider mb-2">
                Status breakdown
              </h3>
              <div class="space-y-1.5 mb-5">
                <div class="flex items-center justify-between text-[12px]">
                  <span class="text-default">Completed</span>
                  <span class="font-mono text-emerald-500">{{ s.completed }}</span>
                </div>
                <div class="flex items-center justify-between text-[12px]">
                  <span class="text-default">Parked (waiting for reply)</span>
                  <span class="font-mono text-accent">{{ s.parked }}</span>
                </div>
                <div class="flex items-center justify-between text-[12px]">
                  <span class="text-default">Running</span>
                  <span class="font-mono text-accent">{{ s.running }}</span>
                </div>
                <div class="flex items-center justify-between text-[12px]">
                  <span class="text-default">Canceled</span>
                  <span class="font-mono text-muted">{{ s.canceled }}</span>
                </div>
                <div class="flex items-center justify-between text-[12px]">
                  <span class="text-default">Errored</span>
                  <span class="font-mono text-red-500">{{ s.errored }}</span>
                </div>
              </div>

              @if (s.top_nodes.length > 0) {
                <h3 class="text-[11px] font-semibold text-muted uppercase tracking-wider mb-2">
                  Most executed nodes
                </h3>
                <ul class="space-y-1">
                  @for (n of s.top_nodes; track n.node_id) {
                    <li
                      class="flex items-center justify-between px-3 py-2 rounded bg-app border border-subtle text-[12px]"
                    >
                      <div class="flex flex-col">
                        <span class="text-default font-semibold" [title]="n.node_id">{{
                          nodeLabel(n.node_type)
                        }}</span>
                      </div>
                      <span class="font-mono text-accent">{{ n.executions }}×</span>
                    </li>
                  }
                </ul>
              }
            }
          }
        </div>
      </div>
    </div>
  `,
})
export class ChatbotStatsModalComponent {
  protected readonly nodeLabel = nodeTypeLabel;

  private readonly api = inject(ChatbotsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input({ required: true }) botId!: string;

  @Output() readonly close = new EventEmitter<void>();

  readonly loading = signal<boolean>(true);
  readonly error = signal<string | null>(null);
  readonly stats = signal<ChatbotStats | null>(null);

  ngOnInit(): void {
    this.api
      .getStats(this.botId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this.stats.set(s);
          this.loading.set(false);
        },
        error: (err) => {
          this.error.set(extractApiError(err) ?? 'Failed to load stats.');
          this.loading.set(false);
        },
      });
  }
}

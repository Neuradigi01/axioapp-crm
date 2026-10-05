import { CommonModule, DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  HostListener,
  Input,
  Output,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '@shared/components/toast/toast.service';
import { ConfirmDialogService } from '../../../shared/confirm-dialog/confirm-dialog.service';

import { ChatbotVersionRead, ChatbotsApiService } from '../../chatbots-api.service';

/**
 * Version history modal — lists prior saves of the current bot and
 * lets the operator restore any of them. Every Save writes a row to
 * ``tbl_chatbot_versions``, so this is just a paged list + a POST
 * to the existing rollback endpoint.
 *
 * Rollback replaces graph + trigger_config in-place; the caller
 * (builder page) reloads the bot on ``(restored)`` so the canvas
 * shows the restored state.
 */
@Component({
  selector: 'app-chatbot-history-modal',
  standalone: true,
  imports: [CommonModule, DatePipe, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      (click)="requestClose()"
    >
      <div
        class="bg-surface border border-subtle rounded-xl w-[560px] max-w-[92vw] max-h-[85vh] flex flex-col shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cb_history_title"
        (click)="$event.stopPropagation()"
      >
        <header class="flex items-center gap-3 px-5 py-4 border-b border-subtle">
          <span
            class="w-8 h-8 rounded-lg bg-accent-soft text-accent inline-flex items-center justify-center"
          >
            <lucide-icon name="clock" size="16"></lucide-icon>
          </span>
          <div class="flex-1">
            <h2 id="cb_history_title" class="text-sm font-semibold text-default">
              Version history
            </h2>
            <p class="text-[11px] text-muted mt-0.5">
              Every save creates a version. Restore any to roll back the graph.
            </p>
          </div>
          <button
            type="button"
            (click)="requestClose()"
            [disabled]="restoring()"
            class="p-1.5 rounded hover:bg-surface-2 text-muted hover:text-default disabled:opacity-40"
            aria-label="Close"
          >
            <lucide-icon name="x" size="16"></lucide-icon>
          </button>
        </header>

        <div class="flex-1 overflow-y-auto">
          @if (loading()) {
            <div class="flex items-center justify-center py-10 text-sm text-muted">
              <lucide-icon name="loader-2" size="14" class="animate-spin mr-2"></lucide-icon>
              Loading history…
            </div>
          } @else if (error()) {
            <div class="p-5 text-sm text-red-500">{{ error() }}</div>
          } @else if (versions().length === 0) {
            <div class="p-10 text-center text-sm text-muted">
              No versions yet. Save the bot to create the first version.
            </div>
          } @else {
            <ul class="divide-y divide-subtle">
              @for (v of versions(); track v.id) {
                <li class="flex items-center gap-3 px-5 py-3 hover:bg-surface-2 transition-colors">
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="text-[13px] font-semibold text-default"
                        >v{{ v.version_number }}</span
                      >
                      @if (v.version_number === currentVersion) {
                        <span
                          class="px-1.5 py-px text-[9px] font-bold uppercase tracking-wider bg-emerald-500/15 text-emerald-500 rounded"
                        >
                          Current
                        </span>
                      }
                    </div>
                    <p class="text-[11px] text-muted mt-0.5">
                      {{ v.created_at | date: 'MMM d, y · h:mm a' }}
                    </p>
                    @if (v.change_note) {
                      <p class="text-[11px] text-default mt-1 italic">{{ v.change_note }}</p>
                    }
                  </div>
                  @if (v.version_number !== currentVersion) {
                    <button
                      type="button"
                      (click)="restore(v)"
                      [disabled]="restoring()"
                      class="px-3 py-1.5 text-[11px] font-semibold rounded-md bg-accent-soft text-accent hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-1"
                    >
                      <lucide-icon name="rotate-ccw" size="11"></lucide-icon>
                      Restore
                    </button>
                  }
                </li>
              }
            </ul>
          }
        </div>
      </div>
    </div>
  `,
})
export class ChatbotHistoryModalComponent {
  private readonly api = inject(ChatbotsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly confirmDialog = inject(ConfirmDialogService);
  private readonly toast = inject(ToastService);

  @Input({ required: true }) botId!: string;
  @Input() currentVersion = 0;
  /** Whether the canvas has unsaved edits — worded into the restore confirm. */
  @Input() hasUnsavedChanges = false;

  @Output() readonly close = new EventEmitter<void>();
  @Output() readonly restored = new EventEmitter<void>();

  readonly loading = signal<boolean>(true);
  readonly error = signal<string | null>(null);
  readonly versions = signal<ChatbotVersionRead[]>([]);
  readonly restoring = signal<boolean>(false);

  ngOnInit(): void {
    this.api
      .listVersions(this.botId, 50)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.versions.set(rows);
          this.loading.set(false);
        },
        error: (err) => {
          this.error.set(extractApiError(err) ?? 'Failed to load history.');
          this.loading.set(false);
        },
      });
  }

  /** True while the restore confirm is up, so Esc doesn't also close us. */
  private confirming = false;

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (!this.confirming) this.requestClose();
  }

  protected requestClose(): void {
    if (!this.restoring()) this.close.emit();
  }

  async restore(v: ChatbotVersionRead): Promise<void> {
    if (this.restoring()) return;
    this.confirming = true;
    let ok = false;
    try {
      ok = await this.confirmDialog.ask({
        title: `Restore version ${v.version_number}?`,
        body: this.hasUnsavedChanges
          ? 'The bot goes back to this version — and your unsaved changes on the canvas are thrown away.'
          : 'The bot goes back to this version. The current version stays in history, so you can restore it again.',
        confirmLabel: 'Restore',
        danger: this.hasUnsavedChanges,
      });
    } finally {
      this.confirming = false;
    }
    if (!ok) return;
    this.restoring.set(true);
    this.api
      .rollback(this.botId, v.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.restoring.set(false);
          this.restored.emit();
          this.close.emit();
        },
        error: (err) => {
          // Toast, not `error` — that slot is the load error and would
          // hide the version list the operator still needs.
          console.error('chatbot.restore.failed', err);
          this.toast.error('Restore failed', { subtitle: extractApiError(err) ?? undefined });
          this.restoring.set(false);
        },
      });
  }
}

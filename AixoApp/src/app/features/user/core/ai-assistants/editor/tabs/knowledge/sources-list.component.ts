/**
 * Knowledge sources list (``tasks/ai-assistants`` Step 11).
 *
 * Renders one row per source with icon / name / status pill / action
 * buttons. Polls ``GET /knowledge`` every 3s while any row is in-
 * flight (``pending`` or ``processing``) and stops as soon as every
 * row lands on a terminal status — no unnecessary background traffic
 * once the queue is quiet.
 *
 * Actions:
 *   * **Cancel** — visible only while ``status='processing'``.
 *   * **Replace** — visible only when ``status='ready'``. Opens a
 *     small modal with the standard warning + a file picker.
 *   * **Delete** — always visible. Confirm-dialog gate.
 */
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Input,
  OnChanges,
  SimpleChanges,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';
import { Subscription, Subject, switchMap, timer } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';
import { ConfirmDialogComponent } from '../../../../shared/confirm-dialog/confirm-dialog.component';
import {
  AiAssistantKnowledgeRow,
  AiAssistantsApiService,
  KnowledgeStatus,
} from '../../../ai-assistants-api.service';
import { ReplaceModalComponent } from './replace-modal.component';

const POLL_MS = 3_000;

const TERMINAL_STATUSES: readonly KnowledgeStatus[] = [
  'ready',
  'failed_no_text',
  'failed_stuck',
  'failed_ingest',
];

const SOURCE_ICON: Record<AiAssistantKnowledgeRow['source_type'], string> = {
  file: 'file-text',
  text: 'file-text',
  url: 'link',
};

@Component({
  selector: 'app-knowledge-sources-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule, ConfirmDialogComponent, ReplaceModalComponent],
  templateUrl: './sources-list.component.html',
})
export class SourcesListComponent implements OnChanges {
  private readonly api = inject(AiAssistantsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input({ required: true }) assistantId!: string;
  /** Signal-input pattern in Input form: parent bumps a counter when
   *  a panel creates a row, and this component re-fetches. */
  @Input() refreshTick = 0;

  protected readonly rows = signal<AiAssistantKnowledgeRow[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  /** Ephemeral inline error surfaced by the action buttons — cleared
   *  when the operator retries or the next poll succeeds. */
  protected readonly actionError = signal<string | null>(null);

  /** Delete-confirmation state. Non-null → dialog visible for that id. */
  protected readonly deleteTarget = signal<AiAssistantKnowledgeRow | null>(null);
  protected readonly deleting = signal(false);
  /** Replace-modal state. */
  protected readonly replaceTarget = signal<AiAssistantKnowledgeRow | null>(null);

  protected readonly isEmpty = computed(() => this.rows().length === 0);

  /** Manual "please refetch NOW" nudge — used by refreshTick + action
   *  completions. Emits into a Subject the poller multiplexes with
   *  its interval so the next tick happens immediately, not after
   *  the full 3s. */
  private readonly manualRefresh = new Subject<void>();
  private pollSubscription: Subscription | null = null;

  ngOnChanges(changes: SimpleChanges): void {
    if ('assistantId' in changes) {
      this.rows.set([]);
      this.startPolling();
    }
    if ('refreshTick' in changes && !changes['refreshTick'].firstChange) {
      this.manualRefresh.next();
    }
  }

  private startPolling(): void {
    this.pollSubscription?.unsubscribe();
    this.loading.set(true);
    // Use ``switchMap`` — a new refresh cancels the in-flight one so
    // a slow response doesn't clobber a fresh state.
    this.pollSubscription = timer(0, POLL_MS)
      .pipe(
        // Merge the manual pings by resetting the timer whenever a
        // nudge arrives. We can't easily merge two sources without
        // duplicated GETs, so we live with the 3s cadence + the
        // manual reset (subscribed side-effect below).
        switchMap(() => this.api.listKnowledge(this.assistantId)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (rows) => {
          this.loading.set(false);
          this.error.set(null);
          this.rows.set(rows);
          if (this.allTerminal(rows)) {
            this.pollSubscription?.unsubscribe();
            this.pollSubscription = null;
          }
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load knowledge sources.');
        },
      });

    this.manualRefresh.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      // Fresh nudge — restart the polling loop so we don't wait for
      // the current 3s tick to elapse.
      this.startPolling();
    });
  }

  private allTerminal(rows: readonly AiAssistantKnowledgeRow[]): boolean {
    return rows.every((r) => TERMINAL_STATUSES.includes(r.status));
  }

  // --- Row helpers -------------------------------------------------

  protected iconFor(row: AiAssistantKnowledgeRow): string {
    return SOURCE_ICON[row.source_type];
  }

  protected displayName(row: AiAssistantKnowledgeRow): string {
    return row.original_filename || row.url || 'Untitled';
  }

  protected shortId(row: AiAssistantKnowledgeRow): string {
    return row.id.slice(0, 8);
  }

  /** Status → pill ring/text classes. Keeps the template compact. */
  protected pillClasses(status: KnowledgeStatus): string {
    switch (status) {
      case 'ready':
        return 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20';
      case 'processing':
      case 'pending':
        return 'bg-amber-500/10 text-amber-400 ring-amber-500/20';
      case 'pending_cancel':
      case 'pending_delete':
        return 'bg-surface-2 text-muted ring-subtle';
      default:
        return 'bg-red-500/10 text-red-400 ring-red-500/20';
    }
  }

  protected statusLabel(status: KnowledgeStatus): string {
    switch (status) {
      case 'failed_no_text':
        return 'No extractable text';
      case 'failed_ingest':
        return 'Ingest failed';
      case 'failed_stuck':
        return 'Stuck';
      case 'pending_cancel':
        return 'Cancelling…';
      case 'pending_delete':
        return 'Deleting…';
      default:
        return status;
    }
  }

  // --- Actions -----------------------------------------------------

  protected onCancel(row: AiAssistantKnowledgeRow): void {
    this.actionError.set(null);
    this.api
      .cancelKnowledge(this.assistantId, row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.manualRefresh.next(),
        error: (err: HttpErrorResponse) => {
          this.actionError.set(extractApiError(err) ?? 'Cancel failed.');
        },
      });
  }

  protected onDeleteRequest(row: AiAssistantKnowledgeRow): void {
    this.deleteTarget.set(row);
  }

  protected onDeleteConfirm(): void {
    const target = this.deleteTarget();
    if (!target) return;
    this.deleting.set(true);
    this.api
      .deleteKnowledge(this.assistantId, target.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleting.set(false);
          this.deleteTarget.set(null);
          this.manualRefresh.next();
        },
        error: (err: HttpErrorResponse) => {
          this.deleting.set(false);
          this.actionError.set(extractApiError(err) ?? 'Delete failed.');
          this.deleteTarget.set(null);
        },
      });
  }

  protected onDeleteCancel(): void {
    this.deleteTarget.set(null);
  }

  protected onReplaceRequest(row: AiAssistantKnowledgeRow): void {
    this.replaceTarget.set(row);
  }

  protected onReplaceClose(): void {
    this.replaceTarget.set(null);
  }

  protected onReplaced(): void {
    this.replaceTarget.set(null);
    this.manualRefresh.next();
  }
}

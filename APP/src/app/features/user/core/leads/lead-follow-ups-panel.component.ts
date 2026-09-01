/**
 * Follow-Up Status panel on the lead-detail page — sir's amber-header
 * log that lists this lead's open follow-up tasks (call / whatsapp /
 * email / meeting / document / other) with mark-done + inline
 * reschedule.
 *
 * Reads via `TasksApiService.listForEntity(lead, id, 'open')` — the
 * same query the dashboard's Today's Follow-ups widget powers off, so
 * writes coming through the Update Status modal (`POST /tasks`) are
 * picked up here on the next load without any special plumbing.
 *
 * `prepend(task)` is the public hook the parent (`LeadDetailPage`)
 * calls from `onUpdateStatusSaved` when the modal returns a
 * `next_follow_up_task_id` — inserts the new row + re-sorts so the
 * rep sees their scheduled follow-up land instantly without a re-fetch.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { Task, TaskFollowupType, TasksApiService } from '../tasks/tasks-api.service';

interface FollowupTypeMeta {
  icon: string;
  label: string;
}

/** Icon + label mapping for the six follow-up channels. `document` and
 *  `other` fall back to `file-text` / `dot` so the row still renders
 *  cleanly when the writer picks the generic case. */
const TYPE_META: Record<TaskFollowupType, FollowupTypeMeta> = {
  call: { icon: 'phone', label: 'Call' },
  whatsapp: { icon: 'message-circle', label: 'WhatsApp' },
  email: { icon: 'mail', label: 'Email' },
  meeting: { icon: 'calendar', label: 'Meeting' },
  document: { icon: 'file-text', label: 'Document' },
  other: { icon: 'dot', label: 'Other' },
};

@Component({
  selector: 'app-lead-follow-ups-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './lead-follow-ups-panel.component.html',
})
export class LeadFollowUpsPanelComponent {
  private readonly api = inject(TasksApiService);
  private readonly destroyRef = inject(DestroyRef);
  /** Belt-and-braces for zoneless mode: HTTP subscribe callbacks fire
   *  outside any tracked execution context; signal writes SHOULD
   *  schedule change detection on their own, but in this component
   *  the initial data was arriving in memory but not repainting until
   *  the next user interaction. Explicit `markForCheck()` after every
   *  async state mutation removes the race. */
  private readonly cdr = inject(ChangeDetectorRef);

  readonly leadId = input.required<string>();

  protected readonly tasks = signal<Task[]>([]);
  /** Start `true` so the panel renders the amber skeleton on mount
   *  instead of flashing the misleading "No follow-ups scheduled"
   *  empty state for the ~200 ms until the first fetch resolves. */
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  protected readonly total = signal(0);
  protected readonly page = signal(1);
  /** Per-row disable + spinner state for mark-done / save-reschedule. */
  protected readonly mutating = signal<ReadonlySet<string>>(new Set());
  /** Task-id of the row currently in reschedule-input mode (only one
   *  at a time — rep opens one, picks a date, saves or cancels). */
  protected readonly rescheduling = signal<string | null>(null);
  /** Local buffer for the datetime-local input while rescheduling.
   *  Cleared on save/cancel. */
  protected readonly rescheduleDraft = signal<string>('');
  /** Transient per-row error banner (mark-done or reschedule failed).
   *  Auto-cleared after 4s by the handler that set it. */
  protected readonly rowError = signal<{ id: string; message: string } | null>(null);

  protected readonly hasMore = computed(() => this.tasks().length < this.total());
  protected readonly skeletonRows = [0, 1, 2] as const;

  constructor() {
    // Reload whenever the lead id changes (parent re-mounts on nav).
    effect(() => {
      const id = this.leadId();
      if (!id) return;
      this.page.set(1);
      this.tasks.set([]);
      this.total.set(0);
      this.load(1);
    });
  }

  /** Public hook — parent calls this after the Update Status modal
   *  submits with a `next_follow_up_task_id`. Inserts + re-sorts by
   *  `due_at` ASC so the newly-scheduled row lands where a fresh
   *  reload would put it. */
  prepend(task: Task): void {
    this.tasks.update((rows) => [task, ...rows].sort(this._compareDueAt));
    this.total.update((n) => n + 1);
  }

  /** Public — parent's `onUpdateStatusSaved` calls this after a modal
   *  submit that included `next_follow_up`. Also used by the amber
   *  header's Refresh button. */
  reload(): void {
    this.page.set(1);
    this.load(1);
  }

  protected loadMore(): void {
    if (this.loading()) return;
    this.load(this.page() + 1);
  }

  protected typeMeta(task: Task): FollowupTypeMeta {
    return task.followup_type ? TYPE_META[task.followup_type] : TYPE_META.other;
  }

  protected isOverdue(task: Task): boolean {
    return (
      task.status === 'open' && task.due_at !== null && new Date(task.due_at).getTime() < Date.now()
    );
  }

  /** Short absolute date + short relative phrase — "23-Aug 10:00
   *  · in 2 days" or "15-Jul 14:00 · overdue by 4 days". Empty when
   *  the task has no due date. */
  protected dueLabel(task: Task): { absolute: string; relative: string } {
    if (task.due_at === null) return { absolute: 'No due date', relative: '' };
    const d = new Date(task.due_at);
    if (Number.isNaN(d.getTime())) return { absolute: 'Invalid', relative: '' };
    const absolute = d.toLocaleString(undefined, {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
    const relative = this._relativeDays(d);
    return { absolute, relative };
  }

  protected markDone(task: Task): void {
    if (this._isMutating(task.id)) return;
    // Optimistic remove — reverts on error via the snapshot below.
    const snapshot = this.tasks();
    this._setMutating(task.id, true);
    this.tasks.update((rows) => rows.filter((r) => r.id !== task.id));
    this.total.update((n) => Math.max(0, n - 1));
    this.api
      .bulkMarkDone([task.id])
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this._setMutating(task.id, false);
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this._setMutating(task.id, false);
          this.tasks.set(snapshot);
          this.total.update((n) => n + 1);
          this._flashRowError(task.id, extractApiError(err) ?? 'Could not mark done.');
          this.cdr.markForCheck();
        },
      });
  }

  protected startReschedule(task: Task): void {
    if (this._isMutating(task.id)) return;
    // Prefill the datetime-local with the task's current due date in
    // the user's local TZ. `<input type="datetime-local">` wants a
    // `YYYY-MM-DDTHH:mm` string with no offset.
    const seed = task.due_at ? this._toLocalInput(new Date(task.due_at)) : this._defaultDue();
    this.rescheduleDraft.set(seed);
    this.rescheduling.set(task.id);
  }

  protected cancelReschedule(): void {
    this.rescheduling.set(null);
    this.rescheduleDraft.set('');
  }

  protected saveReschedule(task: Task): void {
    const raw = this.rescheduleDraft().trim();
    if (!raw) {
      this._flashRowError(task.id, 'Choose a date & time.');
      return;
    }
    const due = new Date(raw);
    if (Number.isNaN(due.getTime())) {
      this._flashRowError(task.id, 'Enter a valid date & time.');
      return;
    }
    // Match backend bounds (now ± 1y/5y) so the rep sees the same
    // rejection the server would emit.
    const now = Date.now();
    if (due.getTime() < now - 365 * 86_400_000 || due.getTime() > now + 5 * 365 * 86_400_000) {
      this._flashRowError(task.id, 'Choose a date within 1 year back and 5 years ahead.');
      return;
    }
    this._setMutating(task.id, true);
    const iso = due.toISOString();
    this.api
      .update(task.id, { due_at: iso })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this._setMutating(task.id, false);
          this.rescheduling.set(null);
          this.rescheduleDraft.set('');
          this.tasks.update((rows) =>
            rows.map((r) => (r.id === updated.id ? updated : r)).sort(this._compareDueAt),
          );
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this._setMutating(task.id, false);
          this._flashRowError(task.id, extractApiError(err) ?? 'Could not reschedule.');
          this.cdr.markForCheck();
        },
      });
  }

  protected onRescheduleInput(value: string): void {
    this.rescheduleDraft.set(value);
  }

  protected isRowMutating(id: string): boolean {
    return this._isMutating(id);
  }

  protected rowErrorFor(id: string): string | null {
    const err = this.rowError();
    return err && err.id === id ? err.message : null;
  }

  private load(page: number): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      // NOTE: `listForEntity` only accepts one status; we query `open`.
      // `missed` tasks (auto-closed after >7d overdue by the nightly
      // cron) are hidden from this panel by design — the amber log is
      // for active follow-ups the rep still needs to act on.
      .listForEntity('lead', this.leadId(), 'open')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.loading.set(false);
          this.total.set(resp.total);
          const sorted = [...resp.items].sort(this._compareDueAt);
          if (page === 1) {
            this.tasks.set(sorted);
          } else {
            // Backend has no cursor pagination; but if a future page
            // arrives via the same endpoint we merge de-duped.
            const seen = new Set(this.tasks().map((t) => t.id));
            const merged = [...this.tasks(), ...sorted.filter((t) => !seen.has(t.id))];
            this.tasks.set(merged.sort(this._compareDueAt));
          }
          this.page.set(page);
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load follow-ups.');
          this.cdr.markForCheck();
        },
      });
  }

  private _setMutating(id: string, on: boolean): void {
    const next = new Set(this.mutating());
    if (on) next.add(id);
    else next.delete(id);
    this.mutating.set(next);
  }

  private _isMutating(id: string): boolean {
    return this.mutating().has(id);
  }

  private _flashRowError(id: string, message: string): void {
    this.rowError.set({ id, message });
    setTimeout(() => {
      const cur = this.rowError();
      if (cur && cur.id === id) {
        this.rowError.set(null);
        this.cdr.markForCheck();
      }
    }, 4000);
  }

  private _compareDueAt = (a: Task, b: Task): number => {
    // Earliest due first; null-due last; tie-break on id for stability.
    if (a.due_at && b.due_at) {
      const av = a.due_at;
      const bv = b.due_at;
      return av < bv ? -1 : av > bv ? 1 : a.id < b.id ? -1 : 1;
    }
    if (a.due_at && !b.due_at) return -1;
    if (!a.due_at && b.due_at) return 1;
    return a.id < b.id ? -1 : 1;
  };

  private _relativeDays(due: Date): string {
    const diffMs = due.getTime() - Date.now();
    const days = Math.round(diffMs / 86_400_000);
    if (days === 0) {
      const hours = Math.round(diffMs / 3_600_000);
      if (hours === 0) return 'now';
      if (hours < 0) return `${Math.abs(hours)}h overdue`;
      return `in ${hours}h`;
    }
    if (days > 0) return `in ${days} day${days === 1 ? '' : 's'}`;
    const overdue = Math.abs(days);
    return `overdue by ${overdue} day${overdue === 1 ? '' : 's'}`;
  }

  private _toLocalInput(d: Date): string {
    const pad = (n: number): string => n.toString().padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
      d.getHours(),
    )}:${pad(d.getMinutes())}`;
  }

  private _defaultDue(): string {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(10, 0, 0, 0);
    return this._toLocalInput(d);
  }
}

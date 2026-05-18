import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import { Task, TasksApiService } from './tasks-api.service';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Header popover that lists the caller's open tasks, grouped by due
 * window: Overdue â†’ Today â†’ Later â†’ No due date. Opens only when the
 * `open` signal-input is true; the parent (header) owns the toggle.
 *
 * Marking a task done removes it from the list (we're filtering by
 * status=open server-side, but the local optimistic flip mirrors that
 * by hiding the row immediately).
 */
type Bucket = 'overdue' | 'today' | 'later' | 'no_due';

interface BucketView {
  id: Bucket;
  label: string;
  items: Task[];
}

@Component({
  selector: 'app-my-tasks-popover',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './my-tasks-popover.component.html',
})
export class MyTasksPopoverComponent {
  private readonly api = inject(TasksApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly open = input<boolean>(false);

  protected readonly items = signal<Task[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly groups = computed<BucketView[]>(() => {
    const now = Date.now();
    const endOfToday = new Date();
    endOfToday.setHours(23, 59, 59, 999);
    const endTs = endOfToday.getTime();

    const buckets: Record<Bucket, Task[]> = {
      overdue: [],
      today: [],
      later: [],
      no_due: [],
    };
    for (const t of this.items()) {
      if (t.due_at === null) {
        buckets.no_due.push(t);
        continue;
      }
      const ts = new Date(t.due_at).getTime();
      if (ts < now) buckets.overdue.push(t);
      else if (ts <= endTs) buckets.today.push(t);
      else buckets.later.push(t);
    }
    const view: BucketView[] = [
      { id: 'overdue', label: 'Overdue', items: buckets.overdue },
      { id: 'today', label: 'Today', items: buckets.today },
      { id: 'later', label: 'Later', items: buckets.later },
      { id: 'no_due', label: 'No due date', items: buckets.no_due },
    ];
    return view.filter((g) => g.items.length > 0);
  });

  protected readonly totalOpen = computed(() => this.items().length);

  constructor() {
    effect(() => {
      // Lazy-load: only fetch when the popover is actually opened.
      if (this.open()) this.reload();
    });
  }

  reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listMine('open')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load your tasks.',
          );
          this.loading.set(false);
        },
      });
  }

  protected markDone(task: Task): void {
    const before = this.items();
    this.items.update((rows) => rows.filter((r) => r.id !== task.id));
    this.api
      .update(task.id, { status: 'done' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        error: (err: HttpErrorResponse) => {
          this.items.set(before);
          this.loadError.set(
            extractApiError(err) ?? 'Could not update task.',
          );
        },
      });
  }

  protected formatDue(iso: string | null): string {
    if (iso === null) return 'â€”';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'â€”';
    return d.toLocaleString(undefined, {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

}

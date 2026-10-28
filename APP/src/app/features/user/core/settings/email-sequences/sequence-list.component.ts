/**
 * Settings → Email Sequences list tab.
 *
 * Table of saved sequences with name, step count, and a compact
 * per-row stats string ("Active 12 · Completed 4 · Paused 1"). The
 * stats are loaded lazily after the main list resolves to avoid a
 * fan-out call burst on initial render; each row fires three small
 * `listEnrollments(size=1)` calls and reads only the `total` field.
 *
 * Permission model mirrors templates: the tab is gated on
 * `email.read` (anyone in the workspace can browse); Create / Edit /
 * Delete affordances are gated on `email.sequences.manage`.
 */
import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { forkJoin } from 'rxjs';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../../auth/auth.service';
import {
  EmailSequence,
  EmailSequencesApiService,
} from '../../services/email-sequences-api.service';

interface SequenceStats {
  active: number;
  completed: number;
  paused_on_reply: number;
}

@Component({
  selector: 'app-email-sequences-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, LucideAngularModule, ReactiveFormsModule, RouterLink],
  templateUrl: './sequence-list.component.html',
})
export class EmailSequencesListComponent implements OnInit {
  private readonly api = inject(EmailSequencesApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly sequences = signal<EmailSequence[] | null>(null);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly inlineError = signal<string | null>(null);

  /** sequence_id → stats. Filled in by `_loadStats` after the main
   *  list resolves. Missing keys render as "…". */
  protected readonly stats = signal<Record<string, SequenceStats>>({});

  protected readonly deleting = signal<string | null>(null);
  protected readonly confirmDelete = signal<EmailSequence | null>(null);

  protected readonly canManage = computed(() => this.auth.hasPermission('email.sequences.manage'));

  protected readonly searchCtrl = new FormControl<string>('', {
    nonNullable: true,
  });

  protected readonly emptyState = computed(() => (this.sequences()?.length ?? 0) === 0);

  ngOnInit(): void {
    this._load('');
    this.searchCtrl.valueChanges
      .pipe(debounceTime(250), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((value) => this._load(value.trim()));
  }

  refresh(): void {
    this._load(this.searchCtrl.value.trim());
  }

  openCreate(): void {
    this.router.navigate(['/user/settings/email-sequences/new']);
  }

  openDelete(s: EmailSequence): void {
    this.inlineError.set(null);
    this.confirmDelete.set(s);
  }

  cancelDelete(): void {
    if (this.deleting() !== null) return;
    this.confirmDelete.set(null);
  }

  confirmDeleteAction(): void {
    const target = this.confirmDelete();
    if (!target || this.deleting() !== null) return;
    this.deleting.set(target.id);
    this.api
      .deleteSequence(target.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleting.set(null);
          this.confirmDelete.set(null);
          this.refresh();
        },
        error: (err: HttpErrorResponse) => {
          this.deleting.set(null);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  private _load(q: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listSequences({ q: q || undefined })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.sequences.set(resp.items);
          this.loading.set(false);
          this._loadStats(resp.items);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err));
        },
      });
  }

  /** For each visible sequence, fan out three lightweight `size=1`
   *  enrollment calls to read `total` per state. Best-effort — a
   *  failure leaves the row's stats undefined and renders "…". */
  private _loadStats(rows: EmailSequence[]): void {
    if (rows.length === 0) return;
    for (const seq of rows) {
      forkJoin({
        active: this.api.listEnrollments({
          sequence_id: seq.id,
          state: 'active',
          size: 1,
        }),
        completed: this.api.listEnrollments({
          sequence_id: seq.id,
          state: 'completed',
          size: 1,
        }),
        paused_on_reply: this.api.listEnrollments({
          sequence_id: seq.id,
          state: 'paused_on_reply',
          size: 1,
        }),
      })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: ({ active, completed, paused_on_reply }) => {
            this.stats.update((current) => ({
              ...current,
              [seq.id]: {
                active: active.total,
                completed: completed.total,
                paused_on_reply: paused_on_reply.total,
              },
            }));
          },
          error: () => {
            // Leave the row's stats undefined — the template renders
            // "…" so the operator sees something happened.
          },
        });
    }
  }
}

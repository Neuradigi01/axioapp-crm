import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { forkJoin, of } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { ContactsApiService } from '../contacts/contacts-api.service';
import {
  ItemMovedEvent,
  PipelineItem,
} from '../pipelines/pipelines-api.service';
import { PipelineBoardComponent } from '../pipelines/pipeline-board.component';
import { PipelineListComponent } from '../pipelines/pipeline-list.component';
import { LeadCardComponent } from './lead-card.component';
import { LeadFormModalComponent } from './lead-form-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import {
  Lead,
  LeadCreate,
  LeadStatus,
  LeadUpdate,
  LeadsApiService,
} from './leads-api.service';

/**
 * Top-level Leads page.
 *
 * Tabs:
 *   - **Pipeline** â€” wraps `<app-pipeline-board pipelineKey="leads">`
 *     and feeds it the loaded leads. The lead-card template projects
 *     into each kanban card. `(itemMoved)` calls the move-stage
 *     endpoint; on error we revert the optimistic local mutation.
 *   - **List** â€” wraps `<app-pipeline-list>` for the same data with
 *     the same `itemMoved` semantics.
 *
 * Contact info on each card comes from a one-shot
 * `forkJoin(contactsApi.get(id))` after the leads load â€” keeps the
 * card component dumb and avoids it issuing its own HTTP per render.
 */
type View = 'pipeline' | 'list';

interface ContactSummary {
  id: string;
  full_name: string;
  phone: string | null;
  source: string | null;
}

@Component({
  selector: 'app-leads-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    LucideAngularModule,
    PipelineBoardComponent,
    PipelineListComponent,
    LeadCardComponent,
    LeadFormModalComponent,
  ],
  templateUrl: './leads.page.html',
})
export class LeadsPageComponent {
  private readonly api = inject(LeadsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly leads = signal<Lead[]>([]);
  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);

  readonly view = signal<View>('pipeline');
  readonly searchControl = new FormControl('', { nonNullable: true });
  readonly sourceControl = new FormControl('', { nonNullable: true });

  private readonly q = toSignal(
    this.searchControl.valueChanges.pipe(debounceTime(200), distinctUntilChanged()),
    { initialValue: '' },
  );
  private readonly sourceFilter = toSignal(
    this.sourceControl.valueChanges.pipe(distinctUntilChanged()),
    { initialValue: '' },
  );

  readonly contactsById = signal<Record<string, ContactSummary>>({});

  readonly sourceOptions = computed(() => {
    const set = new Set<string>();
    for (const c of Object.values(this.contactsById())) {
      if (c.source) set.add(c.source);
    }
    return [...set].sort();
  });

  /** "X total Â· Y new today" â€” header subtitle. */
  readonly totalCount = computed(() => this.leads().length);
  readonly newTodayCount = computed(() => {
    const todayKey = this.todayKey();
    return this.leads().filter(
      (l) => this.dateKey(l.created_at) === todayKey,
    ).length;
  });

  private todayKey(): string {
    return this.dateKey(new Date().toISOString());
  }

  private dateKey(iso: string): string {
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  /** Modal: null = closed, undefined = create, Lead = edit. */
  readonly modalState = signal<Lead | null | undefined>(null);
  readonly modalOpen = computed(() => this.modalState() !== null);
  readonly editingLead = computed<Lead | null>(() => {
    const v = this.modalState();
    return v === undefined ? null : (v ?? null);
  });
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);

  /** Cast Lead[] to PipelineItem[] for the board/list inputs. */
  readonly pipelineItems = computed<PipelineItem[]>(
    () => this.leads() as PipelineItem[],
  );

  constructor() {
    this.reload();

    // Filter changes trigger re-fetch.
    this.searchControl.valueChanges
      .pipe(debounceTime(200), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.reload());
    this.sourceControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.reload());

    // Whenever leads change, fetch any contacts we don't already have cached.
    effect(() => {
      const ids = new Set(this.leads().map((l) => l.contact_id));
      const cache = this.contactsById();
      const missing = [...ids].filter((id) => !cache[id]);
      if (missing.length === 0) return;
      this.fetchContacts(missing);
    });
  }

  protected setView(v: View): void {
    this.view.set(v);
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({
        q: this.q() || undefined,
        source: this.sourceFilter() || undefined,
        size: 100,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.leads.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.leads.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load leads.');
        },
      });
  }

  protected onItemMoved(event: ItemMovedEvent): void {
    const before = this.leads();
    // Optimistic local update so the kanban doesn't flicker.
    this.leads.update((rows) =>
      rows.map((r) =>
        r.id === event.itemId ? { ...r, pipeline_stage: event.toStage } : r,
      ),
    );
    this.api
      .moveStage(event.itemId, event.toStage)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.leads.update((rows) =>
            rows.map((r) => (r.id === updated.id ? updated : r)),
          );
        },
        error: (err: HttpErrorResponse) => {
          this.leads.set(before);
          this.loadError.set(extractApiError(err) ?? 'Could not move lead.');
        },
      });
  }

  protected openCreate(): void {
    this.formError.set(null);
    this.modalState.set(undefined);
  }

  protected openEdit(lead: Lead): void {
    this.formError.set(null);
    this.modalState.set(lead);
  }

  protected closeModal(): void {
    this.modalState.set(null);
    this.formError.set(null);
    this.submitting.set(false);
  }

  protected onSave(event: {
    create?: LeadCreate;
    update?: LeadUpdate;
    moveStageTo?: string;
  }): void {
    if (event.create) {
      this.submitCreate(event.create);
    } else if (event.update) {
      const existing = this.editingLead();
      if (existing) this.submitUpdate(existing.id, event.update, event.moveStageTo);
    }
  }

  protected contactFor(id: string): ContactSummary | null {
    return this.contactsById()[id] ?? null;
  }

  protected statusFor(status: LeadStatus): string {
    return status;
  }

  private submitCreate(payload: LeadCreate): void {
    this.submitting.set(true);
    this.formError.set(null);
    this.api
      .create(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.submitting.set(false);
          this.closeModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.formError.set(extractApiError(err) ?? 'Could not create lead.');
        },
      });
  }

  private submitUpdate(id: string, payload: LeadUpdate, moveStageTo?: string): void {
    this.submitting.set(true);
    this.formError.set(null);
    const update$ = this.api.update(id, payload);
    const final$ = moveStageTo
      ? update$.pipe(switchMap(() => this.api.moveStage(id, moveStageTo)))
      : update$;
    final$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.submitting.set(false);
          this.closeModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.formError.set(extractApiError(err) ?? 'Could not save lead.');
        },
      });
  }

  private fetchContacts(ids: string[]): void {
    forkJoin(
      ids.map((id) =>
        this.contactsApi.get(id).pipe(catchError(() => of(null))),
      ),
    )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((results) => {
        this.contactsById.update((cache) => {
          const next = { ...cache };
          for (const c of results) {
            if (c) {
              next[c.id] = {
                id: c.id,
                full_name: c.full_name,
                phone: c.phone,
                source: c.source,
              };
            }
          }
          return next;
        });
      });
  }

}

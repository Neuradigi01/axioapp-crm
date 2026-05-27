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
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { FurnitureAuthService } from '../auth/auth.service';
import { forkJoin, of } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { ContactsApiService } from '../contacts/contacts-api.service';
import {
  ItemMovedEvent,
  PipelineItem,
} from '../pipelines/pipelines-api.service';
import { PipelineBoardComponent } from '../pipelines/pipeline-board.component';
import { PipelineListComponent } from '../pipelines/pipeline-list.component';
import { RelativeTimePipe } from '../shared/pipes/relative-time.pipe';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import { LeadCardComponent } from './lead-card.component';
import { LeadFormModalComponent } from './lead-form-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import {
  Lead,
  LeadCreate,
  LeadSortKey,
  LeadStatus,
  LeadUpdate,
  LeadsApiService,
  SortOrder,
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
    RouterLink,
    LucideAngularModule,
    PipelineBoardComponent,
    PipelineListComponent,
    LeadCardComponent,
    LeadFormModalComponent,
    RelativeTimePipe,
  ],
  templateUrl: './leads.page.html',
})
export class LeadsPageComponent {
  private readonly api = inject(LeadsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly auth = inject(FurnitureAuthService);
  private readonly usersDir = inject(UsersDirectoryService);

  /** Gates the "Import" header button; backend enforces too. */
  protected readonly canImport = computed(() =>
    this.auth.currentPermissions().includes('leads.import'),
  );

  readonly leads = signal<Lead[]>([]);
  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);

  readonly view = signal<View>('pipeline');
  readonly searchControl = new FormControl('', { nonNullable: true });
  readonly sourceControl = new FormControl('', { nonNullable: true });
  /** Assignee filter. `''` = all; `'me'` resolves to current user;
   * `'unassigned'` filters `assigned_to_id IS NULL`; UUID = that user. */
  readonly assigneeControl = new FormControl<string>('', { nonNullable: true });
  /** Status chip filter: `''` = all, otherwise `active | won | lost`. */
  readonly statusControl = new FormControl<string>('', { nonNullable: true });

  /** Sort state — backend whitelist is created_at / last_activity_at /
   * contact_name. Default newest-created first, matches the prior server
   * default so existing users see no change. */
  readonly sortKey = signal<LeadSortKey>('created_at');
  readonly sortOrder = signal<SortOrder>('desc');

  /** "No activity in N days" chip — translates to `last_activity_lt`. */
  readonly noActivityFilter = signal<'' | '7d' | '14d' | '30d'>('');

  /** Visibility scope: which leads to show before any other filter.
   * Junior reps default to "mine" and don't see the toggle; managers
   * default to "team"; admin/owner default to "all". */
  readonly scope = signal<'mine' | 'team' | 'all'>(this.defaultScopeForRole());

  /** Cached user list for the assignee dropdown. */
  readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  /** Owner-id → "Full Name" lookup so list rows can render a name
   * without round-tripping per row. */
  readonly userMap = computed(() => {
    const map = new Map<string, string>();
    for (const u of this.users()) map.set(u.id, u.full_name);
    return map;
  });

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
    this.assigneeControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.reload());
    this.statusControl.valueChanges
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

    // Honour `/user/leads?new=1` (used by the global quick-add FAB) so
    // landing on the page from anywhere in the app drops the user
    // straight into the create-lead modal. Strip the param after
    // consuming it so a refresh doesn't re-open.
    this.route.queryParamMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((params) => {
        if (params.get('new') !== null && this.modalState() === null) {
          this.openCreate();
          this.router.navigate([], {
            relativeTo: this.route,
            queryParams: { new: null },
            queryParamsHandling: 'merge',
            replaceUrl: true,
          });
        }
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
        status: (this.statusControl.value as LeadStatus) || undefined,
        assigned_to: this.resolveAssignee(),
        last_activity_lt: this.resolveNoActivityCutoff() ?? undefined,
        sort: this.sortKey(),
        order: this.sortOrder(),
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

  /** Resolve the assignee filter to a value the backend understands.
   * `''` (no filter) → undefined. `'me'` → current user id. `'unassigned'`
   * → undefined (special-case handled in Step 3 with a dedicated server
   * param; for now we surface "All" rows when picked, so the chip is
   * visible but inert until that lands). UUID → that UUID. */
  private resolveAssignee(): string | undefined {
    const raw = this.assigneeControl.value;
    if (!raw) return undefined;
    if (raw === 'me') return this.auth.currentUserId() ?? undefined;
    if (raw === 'unassigned') return undefined;
    return raw;
  }

  /** Translate the no-activity chip to an ISO timestamp the backend
   * `last_activity_lt` param accepts. Returns null when no chip is
   * active so the caller can omit the param. */
  private resolveNoActivityCutoff(): string | null {
    const choice = this.noActivityFilter();
    if (!choice) return null;
    const days = choice === '7d' ? 7 : choice === '14d' ? 14 : 30;
    const cutoff = new Date(Date.now() - days * 86_400_000);
    return cutoff.toISOString();
  }

  protected toggleSort(key: LeadSortKey): void {
    if (this.sortKey() === key) {
      this.sortOrder.update((o) => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      this.sortKey.set(key);
      this.sortOrder.set(key === 'contact_name' ? 'asc' : 'desc');
    }
    this.reload();
  }

  protected setStatus(value: string): void {
    this.statusControl.setValue(value);
  }

  protected setScope(value: 'mine' | 'team' | 'all'): void {
    this.scope.set(value);
    this.reload();
  }

  protected setNoActivity(value: '' | '7d' | '14d' | '30d'): void {
    this.noActivityFilter.set(value);
    this.reload();
  }

  /** Default visibility based on the user's role. Junior reps see only
   * their leads; managers see their team; admin/owner see all. Roles
   * the codebase ships with — Owner, Admin, Sales Manager, Employee
   * etc. — are matched by template name. */
  private defaultScopeForRole(): 'mine' | 'team' | 'all' {
    const role = this.auth.currentRoleName();
    if (!role) return 'mine';
    const r = role.toLowerCase();
    if (r === 'owner' || r === 'admin') return 'all';
    if (r.includes('manager')) return 'team';
    return 'mine';
  }

  /** Whether the scope toggle should be visible. Junior staff get the
   * implicit "mine" default with no toggle — keeps their view focused. */
  protected readonly canChangeScope = computed(() => {
    const role = this.auth.currentRoleName().toLowerCase();
    return role === 'owner' || role === 'admin' || role.includes('manager');
  });

  /** Tailwind class string for a status pill. */
  protected statusClass(s: LeadStatus): string {
    switch (s) {
      case 'won':
        return 'bg-emerald-100 text-emerald-800 ring-emerald-200';
      case 'lost':
        return 'bg-rose-100 text-rose-800 ring-rose-200';
      default:
        return 'bg-blue-100 text-blue-800 ring-blue-200';
    }
  }

  protected statusLabel(s: LeadStatus): string {
    return s === 'active' ? 'Active' : s === 'won' ? 'Won' : 'Lost';
  }

  protected ownerLabel(assignedTo: string | null): string {
    if (!assignedTo) return 'Unassigned';
    return this.userMap().get(assignedTo) ?? 'Unknown';
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

import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import {
  Contact,
  ContactCreate,
  ContactListItem,
  ContactSortKey,
  ContactUpdate,
  ContactsApiService,
  SortOrder,
} from './contacts-api.service';
import { ContactFormModalComponent } from './contact-form-modal.component';
import { FurnitureAuthService } from '../auth/auth.service';
import { RelativeTimePipe } from '../shared/pipes/relative-time.pipe';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import { extractApiError } from '@core/services/api-error.util';
import { initials } from '@core/services/text.util';

@Component({
  selector: 'app-contacts-list-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    LucideAngularModule,
    ContactFormModalComponent,
    RelativeTimePipe,
  ],
  templateUrl: './contacts-list.page.html',
})
export class ContactsListPageComponent {
  protected readonly initials = initials;
  private readonly api = inject(ContactsApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly usersDir = inject(UsersDirectoryService);

  readonly items = signal<ContactListItem[]>([]);
  readonly total = signal<number>(0);
  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);

  readonly page = signal<number>(1);
  readonly size = 25;

  readonly searchControl = new FormControl('', { nonNullable: true });
  readonly sourceControl = new FormControl('', { nonNullable: true });
  readonly tagControl = new FormControl('', { nonNullable: true });
  /** Assignee filter. Empty = all, `'me'` resolves to current user, or a user UUID. */
  readonly assigneeControl = new FormControl<string>('', { nonNullable: true });

  /** Sort state. Defaults match the backend (`created_at desc`). */
  readonly sortKey = signal<ContactSortKey>('created_at');
  readonly sortOrder = signal<SortOrder>('desc');

  /** Cached list of users for the assignee dropdown. */
  readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  /** Owner-id → "Full Name" lookup so the list row can show a name
   * without round-tripping to the backend. Tolerates a missing user
   * (deactivated mid-session) by falling back to "Unknown". */
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
  private readonly tagFilter = toSignal(
    this.tagControl.valueChanges.pipe(distinctUntilChanged()),
    { initialValue: '' },
  );

  /** Distinct source/tag chips for filter dropdowns â€” derived from the loaded page. */
  readonly sourceOptions = computed(() => {
    const set = new Set<string>();
    for (const item of this.items()) {
      if (item.source) set.add(item.source);
    }
    return [...set].sort();
  });

  readonly tagOptions = computed(() => {
    const set = new Set<string>();
    for (const item of this.items()) {
      for (const t of item.tags) set.add(t);
    }
    return [...set].sort();
  });

  readonly totalPages = computed(() => {
    const total = this.total();
    if (total === 0) return 1;
    return Math.ceil(total / this.size);
  });

  /** Modal state: null = closed, undefined = create, Contact = edit. */
  readonly modalState = signal<Contact | null | undefined>(null);
  readonly modalOpen = computed(() => this.modalState() !== null);
  readonly editingContact = computed<Contact | null>(() => {
    const v = this.modalState();
    return v === undefined ? null : (v ?? null);
  });
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);

  constructor() {
    // Initial load â€” runs after the effect below subscribes to the filter signals.
    this.reload();

    // Reactive: any filter change resets to page 1 and re-fetches.
    this.searchControl.valueChanges
      .pipe(debounceTime(200), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.page.set(1);
        this.reload();
      });
    this.sourceControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.page.set(1);
        this.reload();
      });
    this.tagControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.page.set(1);
        this.reload();
      });
    this.assigneeControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.page.set(1);
        this.reload();
      });
  }

  /** Click a sortable header. Same key → flip order; new key → reset to a
   * sensible default (ascending for `full_name`, descending for the
   * timestamp columns where the user usually wants newest first). */
  protected toggleSort(key: ContactSortKey): void {
    if (this.sortKey() === key) {
      this.sortOrder.update((o) => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      this.sortKey.set(key);
      this.sortOrder.set(key === 'full_name' ? 'asc' : 'desc');
    }
    this.page.set(1);
    this.reload();
  }

  /** Resolve the assignee filter to a UUID. `'me'` reads the current user
   * id from `FurnitureAuthService` (populated by `/users/me`). Empty
   * string means "no filter". */
  private resolveAssignee(): string | undefined {
    const raw = this.assigneeControl.value;
    if (!raw) return undefined;
    if (raw === 'me') return this.auth.currentUserId() ?? undefined;
    return raw;
  }

  /** Display label for the Owner column. Tries the cached users
   * directory; falls back to "Unassigned" / "Unknown". */
  protected ownerLabel(assignedTo: string | null): string {
    if (!assignedTo) return 'Unassigned';
    return this.userMap().get(assignedTo) ?? 'Unknown';
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({
        q: this.q() || undefined,
        source: this.sourceFilter() || undefined,
        tag: this.tagFilter() || undefined,
        assigned_to_id: this.resolveAssignee(),
        sort: this.sortKey(),
        order: this.sortOrder(),
        page: this.page(),
        size: this.size,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.total.set(resp.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.total.set(0);
          this.loadError.set(extractApiError(err) ?? 'Could not load contacts.');
          this.loading.set(false);
        },
      });
  }

  protected onRowClick(item: ContactListItem): void {
    this.router.navigate(['/user/contacts', item.id]);
  }

  protected openCreate(): void {
    this.formError.set(null);
    this.modalState.set(undefined);
  }

  protected closeModal(): void {
    this.modalState.set(null);
    this.formError.set(null);
    this.submitting.set(false);
  }

  protected onSave(event: { create?: ContactCreate; update?: ContactUpdate }): void {
    if (event.create) {
      this.submitCreate(event.create);
    } else if (event.update) {
      const existing = this.editingContact();
      if (existing) this.submitUpdate(existing.id, event.update);
    }
  }

  protected goToPage(target: number): void {
    if (target < 1 || target > this.totalPages() || target === this.page()) return;
    this.page.set(target);
    this.reload();
  }


  private submitCreate(payload: ContactCreate): void {
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
          this.formError.set(extractApiError(err) ?? 'Could not create contact.');
        },
      });
  }

  private submitUpdate(id: string, payload: ContactUpdate): void {
    this.submitting.set(true);
    this.formError.set(null);
    this.api
      .update(id, payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.submitting.set(false);
          this.closeModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.formError.set(extractApiError(err) ?? 'Could not save contact.');
        },
      });
  }

}

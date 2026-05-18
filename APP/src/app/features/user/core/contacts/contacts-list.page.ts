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
  ContactUpdate,
  ContactsApiService,
} from './contacts-api.service';
import { ContactFormModalComponent } from './contact-form-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import { initials } from '@core/services/text.util';

@Component({
  selector: 'app-contacts-list-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule, ContactFormModalComponent],
  templateUrl: './contacts-list.page.html',
})
export class ContactsListPageComponent {
  protected readonly initials = initials;
  private readonly api = inject(ContactsApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  readonly items = signal<ContactListItem[]>([]);
  readonly total = signal<number>(0);
  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);

  readonly page = signal<number>(1);
  readonly size = 25;

  readonly searchControl = new FormControl('', { nonNullable: true });
  readonly sourceControl = new FormControl('', { nonNullable: true });
  readonly tagControl = new FormControl('', { nonNullable: true });

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
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({
        q: this.q() || undefined,
        source: this.sourceFilter() || undefined,
        tag: this.tagFilter() || undefined,
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

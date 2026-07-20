import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { Contact, ContactListItem, ContactsApiService } from './contacts-api.service';

/**
 * Modal for the contact-merge action (P5 → U6).
 *
 * The primary contact is passed via `[primary]`. The user searches for
 * a secondary contact by name / phone / email, picks one from the
 * results, and confirms. On confirm we POST `/contacts/{primary}/merge`
 * and emit `merged` (parent refreshes the detail view).
 *
 * The self-row of the results is always hidden — you can't merge a
 * contact into itself, and the backend returns 400 if you try.
 */
@Component({
  selector: 'app-merge-contact-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, LucideAngularModule],
  templateUrl: './merge-contact-modal.component.html',
})
export class MergeContactModalComponent {
  private readonly api = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input({ required: true }) primary!: Contact;

  @Output() readonly cancel = new EventEmitter<void>();
  @Output() readonly merged = new EventEmitter<Contact>();

  protected readonly searchTerm = signal('');
  protected readonly results = signal<ContactListItem[]>([]);
  protected readonly searching = signal(false);
  protected readonly selected = signal<ContactListItem | null>(null);
  protected readonly submitting = signal(false);
  protected readonly error = signal<string | null>(null);

  /** Filter the self-row out of the results — you can't merge a
   *  contact into itself and the backend returns 400 if you try. */
  protected readonly visibleResults = computed(() =>
    this.results().filter((r) => r.id !== this.primary.id),
  );

  private readonly search$ = new Subject<string>();

  constructor() {
    this.search$
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        switchMap((q) => {
          if (!q || q.trim().length < 2) {
            this.searching.set(false);
            return [{ items: [] as ContactListItem[] }];
          }
          this.searching.set(true);
          return this.api.list({ q: q.trim(), size: 10 });
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => {
          this.results.set(resp.items);
          this.searching.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Search failed.');
          this.searching.set(false);
        },
      });
  }

  protected onSearchInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.searchTerm.set(value);
    this.selected.set(null);
    this.search$.next(value);
  }

  protected pickResult(row: ContactListItem): void {
    this.selected.set(row);
  }

  protected clearSelection(): void {
    this.selected.set(null);
  }

  protected onConfirm(): void {
    const secondary = this.selected();
    if (!secondary) return;
    this.submitting.set(true);
    this.error.set(null);
    this.api
      .merge(this.primary.id, secondary.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.submitting.set(false);
          this.merged.emit(resp.primary);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.error.set(extractApiError(err) ?? 'Could not merge contacts.');
        },
      });
  }

  protected onCancel(): void {
    this.cancel.emit();
  }
}

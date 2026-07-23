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
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { ContactListItem, ContactsApiService } from '../../contacts/contacts-api.service';
import { WalkIn } from '../walk-ins-api.service';

/**
 * Payload emitted on confirm — flows straight into the API service's
 * `convert()` body. Walk-in → Lead conversion accepts two link modes:
 *
 *   - `auto` (default) — keep the walk-in's existing contact_id.
 *     Simplest flow; typical when quick-register just created the
 *     contact seconds before.
 *   - `link` (W3) — pick a different existing contact. Used when the
 *     rep mid-visit realised the walk-in belongs to an existing
 *     customer (repeat visitor whose phone dedup missed, or family
 *     member of an existing customer).
 */
export interface ConvertConfirm {
  contact_link_mode: 'auto' | 'link';
  linked_contact_id: string | null;
  notes: string | null;
}

@Component({
  selector: 'app-walkin-convert-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './walkin-convert-modal.component.html',
})
export class WalkinConvertModalComponent {
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly _walkIn = signal<WalkIn | null>(null);
  protected readonly _submitting = signal(false);
  protected readonly _error = signal<string | null>(null);

  @Input() set walkIn(value: WalkIn | null) {
    this._walkIn.set(value);
  }

  @Input() set submitting(v: boolean) {
    this._submitting.set(v);
  }

  @Input() set error(v: string | null) {
    this._error.set(v);
  }

  @Output() readonly confirm = new EventEmitter<ConvertConfirm>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly notesControl = new FormControl<string>('', {
    nonNullable: true,
  });

  // W3 — contact link mode + picker state.
  protected readonly linkMode = signal<'auto' | 'link'>('auto');
  protected readonly contactSearch = new FormControl<string>('', { nonNullable: true });
  protected readonly contactResults = signal<ContactListItem[]>([]);
  protected readonly contactSearching = signal(false);
  protected readonly selectedContact = signal<ContactListItem | null>(null);

  private readonly search$ = new Subject<string>();

  protected readonly canConfirm = computed(() => {
    if (this._submitting()) return false;
    // `link` mode requires a chosen contact; `auto` always allowed.
    if (this.linkMode() === 'link' && !this.selectedContact()) return false;
    return true;
  });

  constructor() {
    // Debounced contact search — only fires while linkMode='link'.
    this.search$
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        switchMap((q) => {
          const trimmed = q.trim();
          if (trimmed.length < 2) {
            this.contactSearching.set(false);
            return [{ items: [] as ContactListItem[] }];
          }
          this.contactSearching.set(true);
          return this.contactsApi.list({ q: trimmed, size: 10 });
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => {
          this.contactResults.set(resp.items);
          this.contactSearching.set(false);
        },
        error: () => this.contactSearching.set(false),
      });

    this.contactSearch.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((v) => this.search$.next(v));
  }

  protected setLinkMode(mode: 'auto' | 'link'): void {
    this.linkMode.set(mode);
    if (mode === 'auto') {
      this.selectedContact.set(null);
      this.contactSearch.setValue('');
      this.contactResults.set([]);
    }
  }

  protected pickContact(row: ContactListItem): void {
    this.selectedContact.set(row);
  }

  protected clearContact(): void {
    this.selectedContact.set(null);
  }

  protected onConfirm(): void {
    if (!this.canConfirm()) return;
    const notes = this.notesControl.value.trim();
    const mode = this.linkMode();
    const linkedId = mode === 'link' ? (this.selectedContact()?.id ?? null) : null;
    this.confirm.emit({
      contact_link_mode: mode,
      linked_contact_id: linkedId,
      notes: notes || null,
    });
  }
}

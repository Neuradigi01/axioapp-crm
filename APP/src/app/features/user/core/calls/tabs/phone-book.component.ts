import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import {
  ContactListItem,
  ContactsApiService,
} from '../../contacts/contacts-api.service';
import {
  CallOutcome,
  CallsApiService,
} from '../calls-api.service';
import { LogCallModalComponent } from '../log-call-modal.component';
import { initials } from '@core/services/text.util';

/**
 * Phone Book tab â€” searchable contacts list with click-to-call. The
 * "Call" button does two things in sequence:
 *   1. opens `tel:<phone>` in a hidden anchor (the device handles dial)
 *   2. opens the LogCallModal pre-filled with the contact id
 */
@Component({
  selector: 'app-call-phone-book-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule, LogCallModalComponent],
  templateUrl: './phone-book.component.html',
})
export class CallPhoneBookTabComponent {
  protected readonly initials = initials;
  private readonly contactsApi = inject(ContactsApiService);
  private readonly callsApi = inject(CallsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly items = signal<ContactListItem[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly outcomes = signal<CallOutcome[]>([]);
  protected readonly modalState = signal<ContactListItem | null>(null);

  protected readonly searchControl = new FormControl('', { nonNullable: true });

  constructor() {
    this.reload();
    this.callsApi
      .listOutcomes()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.outcomes.set(rows),
        error: () => {
          /* leave empty */
        },
      });
    this.searchControl.valueChanges
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(() => this.reload());
  }


  protected avatarBg(id: string): string {
    const palette = [
      'bg-rose-100 text-rose-700',
      'bg-amber-100 text-amber-700',
      'bg-emerald-100 text-emerald-700',
      'bg-sky-100 text-sky-700',
      'bg-violet-100 text-violet-700',
      'bg-fuchsia-100 text-fuchsia-700',
    ];
    let h = 0;
    for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return palette[h % palette.length];
  }

  protected call(contact: ContactListItem): void {
    if (contact.phone) {
      window.location.href = `tel:${contact.phone}`;
    }
    this.modalState.set(contact);
  }

  protected closeModal(): void {
    this.modalState.set(null);
  }

  protected onSaved(): void {
    this.modalState.set(null);
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    const q = this.searchControl.value.trim();
    this.contactsApi
      .list({ q: q || undefined, size: 200 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          // Only show contacts that actually have a phone â€” clicking
          // "Call" on a row without one is a footgun.
          this.items.set(resp.items.filter((c) => !!c.phone));
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loading.set(false);
          this.loadError.set(
            this._extract(err) ?? 'Could not load phone book.',
          );
        },
      });
  }

  private _extract(err: HttpErrorResponse): string | null {
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const candidate =
        (body as { message?: string; detail?: unknown }).message
        ?? (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}

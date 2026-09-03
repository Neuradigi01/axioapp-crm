import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { ContactListItem, ContactsApiService } from '../../contacts/contacts-api.service';
import { CallOutcome, CallsApiService } from '../calls-api.service';
import { CallPickerModalComponent } from '../call-picker-modal.component';
import { LogCallModalComponent } from '../log-call-modal.component';
import { initials } from '@core/services/text.util';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Phone Book tab — searchable contacts list with click-to-call. The
 * "Call" button opens a picker modal offering the free dial paths
 * (WhatsApp / Phone Link / Copy) instead of blindly firing `tel:` —
 * that gave users the ugly Windows "Open Pick an app?" prompt. After
 * the user chooses a path, the LogCallModal opens pre-filled so the
 * call still gets recorded.
 */
@Component({
  selector: 'app-call-phone-book-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    LucideAngularModule,
    CallPickerModalComponent,
    LogCallModalComponent,
  ],
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
  /** Contact currently being *picked* — modal is open showing dial options. */
  protected readonly pickerState = signal<ContactListItem | null>(null);
  /** Contact currently being *logged* — LogCallModal is open, user finishes the log. */
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
      .pipe(debounceTime(200), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.reload());
  }

  protected avatarBg(id: string): string {
    const palette = [
      'bg-red-500/10 text-red-400',
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

  /** Step 1 of the click-to-call flow: open the picker so the user
   *  chooses HOW to call. The picker itself does the actual dial /
   *  clipboard write; we just move to step 2 when it emits `picked`. */
  protected call(contact: ContactListItem): void {
    this.pickerState.set(contact);
  }

  /** Step 2: picker emitted `picked` — close the picker and open the
   *  LogCallModal so the user records the call outcome. */
  protected onPicked(): void {
    const contact = this.pickerState();
    this.pickerState.set(null);
    if (contact) this.modalState.set(contact);
  }

  protected closePicker(): void {
    this.pickerState.set(null);
  }

  protected closeModal(): void {
    this.modalState.set(null);
  }

  protected onSaved(): void {
    this.modalState.set(null);
  }

  /** Monotonic request id — bumped on every `reload()`, checked in
   *  the response callback so a slow earlier response can't overwrite
   *  a faster later one when the search box is typed into rapidly. */
  private reloadSeq = 0;

  protected reload(): void {
    const seq = ++this.reloadSeq;
    this.loading.set(true);
    this.loadError.set(null);
    const q = this.searchControl.value.trim();
    this.contactsApi
      .list({ q: q || undefined, size: 200 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          if (seq !== this.reloadSeq) return;
          // Only show contacts that actually have a phone — clicking
          // "Call" on a row without one is a footgun.
          this.items.set(resp.items.filter((c) => !!c.phone));
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          if (seq !== this.reloadSeq) return;
          this.items.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load phone book.');
        },
      });
  }
}

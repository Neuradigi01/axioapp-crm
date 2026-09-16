import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Output,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { Subject, of } from 'rxjs';
import { catchError, debounceTime, switchMap } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';

import { ContactListItem, ContactsApiService } from '../contacts/contacts-api.service';
import {
  Conversation,
  ConversationChannel,
  ConversationsApiService,
} from './conversations-api.service';

type PickerChannel = Extract<ConversationChannel, 'whatsapp' | 'email'>;

/**
 * Modal shown when the operator clicks *+ New conversation* in the
 * inbox header. The picker lists contacts (search-debounced) and,
 * per active channel, either enables a "Start" click or disables the
 * row with an "Add phone/email first" affordance linking to that
 * contact's edit page.
 *
 * Templates-only send-first-message concerns don't apply here — the
 * server returns the conversation row and the parent lets the
 * existing compose bar take over (which already handles the WhatsApp
 * 24-h session window by forcing the template picker when outside it).
 */
@Component({
  selector: 'app-new-conversation-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, RouterLink],
  templateUrl: './new-conversation-modal.component.html',
})
export class NewConversationModalComponent {
  private readonly contactsApi = inject(ContactsApiService);
  private readonly conversationsApi = inject(ConversationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Output() readonly started = new EventEmitter<Conversation>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly channel = signal<PickerChannel>('whatsapp');
  protected readonly search = signal('');
  protected readonly contacts = signal<ContactListItem[]>([]);
  protected readonly loading = signal(false);
  /** Id of the contact whose thread is being opened — drives the
   *  per-row "Starting…" state and disables all rows during the POST. */
  protected readonly submittingId = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);
  /** Map of `contact_id → existing conversation` on the currently-selected
   *  channel. Populated by a scoped list fetch when the modal opens and
   *  refetched on every channel switch. Drives the "Continue chat"
   *  affordance so the operator can see up-front which contacts already
   *  have an open thread — WhatsApp keys off phone / email keys off the
   *  address, so a "new" thread on the same identifier lands on the
   *  same conversation row (backend is idempotent by design). */
  protected readonly existingByContactId = signal<Map<string, Conversation>>(new Map());

  /** Channel pill labels. WhatsApp / Email are the only manual-start
   *  channels the backend accepts; SMS / IG / FB / web / push are
   *  hidden here so the operator can't try a channel that would 400. */
  protected readonly channels: ReadonlyArray<{
    value: PickerChannel;
    label: string;
    icon: string;
  }> = [
    { value: 'whatsapp', label: 'WhatsApp', icon: 'message-circle' },
    { value: 'email', label: 'Email', icon: 'mail' },
  ];

  private readonly search$ = new Subject<string>();

  /** Chevron shows "Add phone" or "Add email" depending on channel —
   *  computed so the row template stays declarative. */
  protected readonly missingIdentifierLabel = computed(() =>
    this.channel() === 'whatsapp' ? 'Add a phone number' : 'Add an email address',
  );

  constructor() {
    this.loadContacts('');
    // Refetch the existing-conversations index whenever the channel
    // toggle flips. Runs immediately on mount too (effect fires once
    // for the initial 'whatsapp' value).
    effect(() => {
      const ch = this.channel();
      this.loadExistingConversations(ch);
    });
    this.search$
      .pipe(
        debounceTime(200),
        switchMap((q) => {
          this.loading.set(true);
          return this.contactsApi
            .list({ q: q.trim() || undefined, page: 1, size: 50 })
            .pipe(catchError(() => of({ items: [], total: 0, page: 1, size: 0 })));
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((resp) => {
        this.contacts.set(resp.items);
        this.loading.set(false);
      });
  }

  protected onSearchInput(value: string): void {
    this.search.set(value);
    this.search$.next(value);
  }

  protected pickChannel(c: PickerChannel): void {
    if (this.channel() === c) return;
    this.channel.set(c);
    // Clear a stale error when the channel changes — a "no email" 422
    // shouldn't stay pinned once the operator flipped to WhatsApp.
    this.error.set(null);
  }

  /** True when the contact has the identifier the active channel needs. */
  protected hasIdentifier(c: ContactListItem): boolean {
    return this.channel() === 'whatsapp' ? !!c.phone?.trim() : !!c.email?.trim();
  }

  /** What to render on the right side of the row for a valid contact —
   *  the visible phone/email helps the operator confirm they're picking
   *  the right person out of a name collision. */
  protected identifierPreview(c: ContactListItem): string {
    return (this.channel() === 'whatsapp' ? c.phone : c.email) ?? '';
  }

  /** Existing thread for this contact on the current channel, or null.
   *  Consumed by the row template to swap "Start" → "Continue chat" +
   *  render a small last-activity hint. */
  protected existingConversation(c: ContactListItem): Conversation | null {
    return this.existingByContactId().get(c.id) ?? null;
  }

  protected start(c: ContactListItem): void {
    if (!this.hasIdentifier(c)) return;
    if (this.submittingId() !== null) return;
    this.submittingId.set(c.id);
    this.error.set(null);
    this.conversationsApi
      .create(this.channel(), c.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (conv) => {
          this.submittingId.set(null);
          this.started.emit(conv);
        },
        error: (err: HttpErrorResponse) => {
          this.submittingId.set(null);
          this.error.set(extractApiError(err) ?? 'Could not start the conversation.');
        },
      });
  }

  protected close(): void {
    this.cancel.emit();
  }

  private loadContacts(q: string): void {
    this.loading.set(true);
    this.contactsApi
      .list({ q: q || undefined, page: 1, size: 50 })
      .pipe(
        catchError(() => of({ items: [], total: 0, page: 1, size: 0 })),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((resp) => {
        this.contacts.set(resp.items);
        this.loading.set(false);
      });
  }

  /** Pull the org's open conversations on `channel` and index them by
   *  contact id. Runs once per channel switch — cheap best-effort call:
   *  a failure just leaves the map empty and every row renders the
   *  regular "Start" label rather than blocking the picker. */
  private loadExistingConversations(channel: PickerChannel): void {
    this.conversationsApi
      .list({ channel, page: 1, size: 500 })
      .pipe(
        catchError(() => of({ items: [], total: 0, page: 1, size: 0 })),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((resp) => {
        const map = new Map<string, Conversation>();
        for (const conv of resp.items) {
          if (conv.contact_id) map.set(conv.contact_id, conv);
        }
        this.existingByContactId.set(map);
      });
  }
}

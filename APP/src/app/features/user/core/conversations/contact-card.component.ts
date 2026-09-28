import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { Subject, catchError, debounceTime, of, switchMap } from 'rxjs';

import { FurnitureAuthService } from '../auth/auth.service';
import { ContactListItem, ContactsApiService } from '../contacts/contacts-api.service';

/** Name the backend gives contacts auto-created from a WhatsApp number
 *  whose sender had no profile name (see
 *  `conversations/service.py::UNKNOWN_WHATSAPP_CONTACT_NAME`). */
const UNKNOWN_CONTACT_NAME = 'Unknown WhatsApp contact';

type CardMode = 'view' | 'rename' | 'save' | 'link';

/**
 * Details-rail contact card. Linked conversation → name + "Open
 * contact" + inline rename (prompted when the name is still the
 * auto-generated placeholder). Unlinked → "Save as contact" (new
 * contact from the conversation's number) or "Link existing" (search
 * picker). Emits intents only; the page owns the API calls.
 */
@Component({
  selector: 'app-conversation-contact-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, LucideAngularModule],
  template: `
    <section class="flex flex-col gap-2">
      <p class="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted">Contact</p>

      @switch (mode()) {
        @case ('rename') {
          <form class="flex items-center gap-1.5" (ngSubmit)="submitName('rename')">
            <input
              type="text"
              name="contactName"
              [(ngModel)]="draftName"
              maxlength="255"
              placeholder="Contact name"
              class="min-w-0 flex-1 rounded-md border border-subtle bg-surface px-2 py-1.5 text-sm text-default focus:border-accent focus:outline-none"
            />
            <button
              type="submit"
              [disabled]="!draftName.trim() || busy"
              class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent text-white disabled:opacity-40"
              aria-label="Save name"
            >
              <lucide-icon name="check" class="h-4 w-4" />
            </button>
            <button
              type="button"
              (click)="mode.set('view')"
              class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted hover:bg-surface-2"
              aria-label="Cancel"
            >
              <lucide-icon name="x" class="h-4 w-4" />
            </button>
          </form>
        }
        @case ('save') {
          <form class="flex flex-col gap-1.5" (ngSubmit)="submitName('save')">
            <input
              type="text"
              name="newContactName"
              [(ngModel)]="draftName"
              maxlength="255"
              placeholder="Contact name"
              class="rounded-md border border-subtle bg-surface px-2 py-1.5 text-sm text-default focus:border-accent focus:outline-none"
            />
            <p class="truncate font-mono text-[11px] text-muted">{{ handle }}</p>
            <div class="flex gap-1.5">
              <button
                type="submit"
                [disabled]="!draftName.trim() || busy"
                class="inline-flex h-8 items-center gap-1.5 rounded-md bg-accent px-3 text-xs font-semibold text-white disabled:opacity-40"
              >
                <lucide-icon name="check" class="h-3.5 w-3.5" />
                Save contact
              </button>
              <button
                type="button"
                (click)="mode.set('view')"
                class="h-8 rounded-md px-3 text-xs text-muted hover:bg-surface-2"
              >
                Cancel
              </button>
            </div>
          </form>
        }
        @case ('link') {
          <div class="flex flex-col gap-1.5">
            <div class="relative">
              <lucide-icon
                name="search"
                class="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint"
              />
              <input
                type="search"
                [ngModel]="query()"
                (ngModelChange)="onQuery($event)"
                placeholder="Search contacts…"
                class="w-full rounded-md border border-subtle bg-surface py-1.5 pl-7 pr-2 text-sm text-default focus:border-accent focus:outline-none"
              />
            </div>
            <div class="max-h-48 overflow-y-auto rounded-md border border-subtle">
              @if (searching()) {
                <p class="px-3 py-2 text-xs text-muted">Searching…</p>
              } @else {
                @for (c of results(); track c.id) {
                  <button
                    type="button"
                    (click)="link.emit(c.id)"
                    [disabled]="busy"
                    class="flex w-full flex-col items-start px-3 py-2 text-left hover:bg-surface-2 disabled:opacity-40"
                  >
                    <span class="w-full truncate text-sm text-default">{{ c.full_name }}</span>
                    @if (c.phone || c.email) {
                      <span class="w-full truncate text-[11px] text-muted">
                        {{ c.phone || c.email }}
                      </span>
                    }
                  </button>
                } @empty {
                  <p class="px-3 py-2 text-xs text-muted">No contacts found.</p>
                }
              }
            </div>
            <button
              type="button"
              (click)="mode.set('view')"
              class="self-start rounded-md px-2 py-1 text-xs text-muted hover:bg-surface-2"
            >
              Cancel
            </button>
          </div>
        }
        @default {
          @if (contactId) {
            <div class="flex items-center gap-2">
              <span class="min-w-0 flex-1 truncate text-sm font-medium text-default">
                {{ isPlaceholder() ? 'No name yet' : contactName }}
              </span>
              @if (canWrite()) {
                <button
                  type="button"
                  (click)="startRename()"
                  class="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted hover:text-default hover:bg-surface-2"
                  title="Edit name"
                  aria-label="Edit contact name"
                >
                  <lucide-icon name="pencil" class="h-3.5 w-3.5" />
                </button>
              }
              <a
                [routerLink]="['/user/contacts', contactId]"
                class="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted hover:text-default hover:bg-surface-2"
                title="Open contact"
                aria-label="Open contact"
              >
                <lucide-icon name="external-link" class="h-3.5 w-3.5" />
              </a>
            </div>
            @if (isPlaceholder() && canWrite()) {
              <button
                type="button"
                (click)="startRename()"
                class="inline-flex items-center gap-1.5 self-start rounded-md border border-dashed border-subtle px-2.5 py-1 text-xs font-medium text-accent hover:bg-surface-2"
              >
                <lucide-icon name="user-plus" class="h-3.5 w-3.5" />
                Add a name
              </button>
            }
          } @else if (canWrite()) {
            <p class="text-xs text-muted">This number isn't saved as a contact yet.</p>
            <div class="flex flex-wrap gap-1.5">
              <button
                type="button"
                (click)="startSave()"
                class="inline-flex h-8 items-center gap-1.5 rounded-md bg-accent px-3 text-xs font-semibold text-white hover:brightness-95"
              >
                <lucide-icon name="user-plus" class="h-3.5 w-3.5" />
                Save as contact
              </button>
              <button
                type="button"
                (click)="startLink()"
                class="inline-flex h-8 items-center gap-1.5 rounded-md border border-subtle px-3 text-xs font-medium text-default hover:bg-surface-2"
              >
                <lucide-icon name="link" class="h-3.5 w-3.5" />
                Link existing
              </button>
            </div>
          } @else {
            <p class="text-xs text-muted">Not saved as a contact.</p>
          }
        }
      }
    </section>
  `,
})
export class ConversationContactCardComponent implements OnChanges {
  private readonly contactsApi = inject(ContactsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  @Input() contactId: string | null = null;
  @Input() contactName: string | null = null;
  /** Phone / email shown under the name field when saving. */
  @Input() handle: string | null = null;
  /** True while the parent's request is in flight — disables submit. */
  @Input() busy = false;

  @Output() readonly saveNew = new EventEmitter<string>();
  @Output() readonly link = new EventEmitter<string>();
  @Output() readonly rename = new EventEmitter<string>();

  protected readonly canWrite = computed(() => this.auth.hasPermission('contacts.write'));
  protected readonly mode = signal<CardMode>('view');
  protected readonly query = signal('');
  protected readonly results = signal<ContactListItem[]>([]);
  protected readonly searching = signal(false);
  protected draftName = '';

  private readonly search$ = new Subject<string>();

  constructor() {
    this.search$
      .pipe(
        debounceTime(200),
        switchMap((q) => {
          this.searching.set(true);
          return this.contactsApi
            .list({ q: q.trim() || undefined, page: 1, size: 20, exclude_anonymised: true })
            .pipe(catchError(() => of({ items: [] as ContactListItem[] })));
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((resp) => {
        this.results.set(resp.items);
        this.searching.set(false);
      });
  }

  protected isPlaceholder(): boolean {
    const name = (this.contactName ?? '').trim();
    return !name || name === UNKNOWN_CONTACT_NAME || name === (this.handle ?? '').trim();
  }

  protected startRename(): void {
    this.draftName = this.isPlaceholder() ? '' : (this.contactName ?? '');
    this.mode.set('rename');
  }

  protected startSave(): void {
    this.draftName = '';
    this.mode.set('save');
  }

  protected startLink(): void {
    // Prefill with the conversation's number so a contact that already
    // owns it surfaces first.
    this.query.set(this.handle ?? '');
    this.mode.set('link');
    this.search$.next(this.handle ?? '');
  }

  protected onQuery(q: string): void {
    this.query.set(q);
    this.search$.next(q);
  }

  protected submitName(kind: 'rename' | 'save'): void {
    const name = this.draftName.trim();
    if (!name) return;
    (kind === 'rename' ? this.rename : this.saveNew).emit(name);
  }

  /** A successful save / link / rename changes the linked contact or
   *  its name — drop back to the read view. A failed request leaves the
   *  inputs untouched so the operator's draft survives. */
  ngOnChanges(changes: SimpleChanges): void {
    if (changes['contactId'] || changes['contactName']) {
      this.mode.set('view');
    }
  }
}

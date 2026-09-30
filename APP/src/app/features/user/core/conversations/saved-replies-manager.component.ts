import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  HostListener,
  OnInit,
  computed,
  inject,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../auth/auth.service';
import { SavedReply } from './conversations-api.service';
import { SavedRepliesStore } from './saved-replies.store';

const SHORTCUT_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;

/**
 * Saved-replies manager modal: list, search, create, edit, delete.
 * Anyone who can reply may create; editing / deleting someone else's
 * reply needs `settings.conversations.manage` (the backend enforces the
 * same rule — the UI just hides the buttons).
 */
@Component({
  selector: 'app-saved-replies-manager',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, LucideAngularModule],
  template: `
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      (click)="dismissed.emit()"
    >
      <div
        class="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl border border-subtle bg-surface shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-label="Saved replies"
        (click)="$event.stopPropagation()"
      >
        <div class="flex items-center justify-between border-b border-subtle px-4 py-3">
          <div>
            <h2 class="text-sm font-semibold text-default">Saved replies</h2>
            <p class="text-xs text-muted">
              Reusable answers for the whole team. Type
              <span class="font-mono text-default">/shortcut</span> in the composer to insert one.
            </p>
          </div>
          <button
            type="button"
            (click)="dismissed.emit()"
            class="rounded p-1 text-muted hover:bg-surface-2 hover:text-default"
            aria-label="Close"
          >
            <lucide-icon name="x" class="h-4 w-4" />
          </button>
        </div>

        <div class="grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-[1fr_1.2fr]">
          <!-- List -->
          <div class="flex min-h-0 flex-col border-b border-subtle md:border-b-0 md:border-r">
            <div class="flex items-center gap-2 p-3">
              <input
                type="search"
                placeholder="Search replies"
                [ngModel]="query()"
                (ngModelChange)="query.set($event)"
                class="w-full rounded-md border border-subtle bg-surface px-2.5 py-1.5 text-sm text-default focus:outline-none focus:ring-1 focus:ring-accent"
              />
              <button
                type="button"
                (click)="startCreate()"
                class="inline-flex shrink-0 items-center gap-1 rounded-md bg-accent px-2.5 py-1.5 text-xs font-semibold text-white hover:brightness-95"
              >
                <lucide-icon name="plus" class="h-3.5 w-3.5" />
                New
              </button>
            </div>
            <ul class="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
              @if (store.loading() && !store.loaded()) {
                <li class="px-2 py-3 text-xs text-muted">Loading…</li>
              } @else if (filtered().length === 0) {
                <li class="px-2 py-3 text-xs text-muted">
                  {{
                    query() ? 'No replies match.' : 'No saved replies yet — create the first one.'
                  }}
                </li>
              }
              @for (r of filtered(); track r.id) {
                <li>
                  <button
                    type="button"
                    (click)="startEdit(r)"
                    [class]="
                      'w-full rounded-md px-2 py-1.5 text-left transition hover:bg-surface-2 ' +
                      (editingId() === r.id ? 'bg-surface-2' : '')
                    "
                  >
                    <span class="flex items-center gap-2">
                      <span class="truncate text-sm font-medium text-default">{{ r.title }}</span>
                      @if (r.shortcut) {
                        <span class="shrink-0 font-mono text-[11px] text-accent"
                          >/{{ r.shortcut }}</span
                        >
                      }
                    </span>
                    <span class="block truncate text-xs text-muted">{{ r.body }}</span>
                  </button>
                </li>
              }
            </ul>
          </div>

          <!-- Editor -->
          <div class="min-h-0 overflow-y-auto p-4">
            @if (formOpen()) {
              <form class="space-y-3" (ngSubmit)="save()">
                <label class="block text-xs">
                  <span class="mb-1 block font-medium text-default">Title</span>
                  <input
                    name="title"
                    maxlength="120"
                    required
                    [disabled]="!canEditCurrent()"
                    [ngModel]="title()"
                    (ngModelChange)="title.set($event)"
                    class="w-full rounded-md border border-subtle bg-surface px-2.5 py-1.5 text-sm text-default focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-60"
                    placeholder="Price list"
                  />
                </label>
                <label class="block text-xs">
                  <span class="mb-1 block font-medium text-default">Shortcut (optional)</span>
                  <div
                    class="flex items-center rounded-md border border-subtle bg-surface focus-within:ring-1 focus-within:ring-accent"
                  >
                    <span class="pl-2.5 font-mono text-sm text-muted">/</span>
                    <input
                      name="shortcut"
                      maxlength="32"
                      [disabled]="!canEditCurrent()"
                      [ngModel]="shortcut()"
                      (ngModelChange)="shortcut.set($event.toLowerCase())"
                      class="w-full bg-transparent px-1 py-1.5 font-mono text-sm text-default focus:outline-none disabled:opacity-60"
                      placeholder="price"
                    />
                  </div>
                  @if (shortcutInvalid()) {
                    <span class="mt-1 block text-[11px] text-red-500">
                      Lowercase letters, numbers, "-" and "_" only (max 32).
                    </span>
                  }
                </label>
                <label class="block text-xs">
                  <span class="mb-1 block font-medium text-default">Message</span>
                  <textarea
                    name="body"
                    rows="7"
                    maxlength="4096"
                    required
                    [disabled]="!canEditCurrent()"
                    [ngModel]="body()"
                    (ngModelChange)="body.set($event)"
                    class="w-full resize-y rounded-md border border-subtle bg-surface px-2.5 py-1.5 text-sm text-default focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-60"
                    placeholder="Hi! Here is our latest price list…"
                  ></textarea>
                </label>
                @if (error(); as err) {
                  <p
                    class="rounded-md border border-red-500/20 bg-red-500/10 px-2.5 py-1.5 text-xs text-red-500"
                  >
                    {{ err }}
                  </p>
                }
                @if (!canEditCurrent()) {
                  <p class="text-[11px] text-muted">
                    Created by a teammate — only they or an admin can change it.
                  </p>
                }
                <div class="flex items-center justify-between gap-2 pt-1">
                  @if (editingId() && canEditCurrent()) {
                    @if (confirmingDelete()) {
                      <span class="flex items-center gap-2 text-xs text-default">
                        Delete this reply?
                        <button
                          type="button"
                          (click)="remove()"
                          [disabled]="busy()"
                          class="rounded-md bg-red-500 px-2 py-1 font-semibold text-white hover:bg-red-600 disabled:opacity-60"
                        >
                          Delete
                        </button>
                        <button
                          type="button"
                          (click)="confirmingDelete.set(false)"
                          class="rounded-md px-2 py-1 text-muted hover:text-default"
                        >
                          Keep
                        </button>
                      </span>
                    } @else {
                      <button
                        type="button"
                        (click)="confirmingDelete.set(true)"
                        class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-red-500 hover:bg-red-500/10"
                      >
                        <lucide-icon name="trash-2" class="h-3.5 w-3.5" />
                        Delete
                      </button>
                    }
                  } @else {
                    <span></span>
                  }
                  @if (canEditCurrent()) {
                    <div class="flex gap-2">
                      <button
                        type="button"
                        (click)="cancelForm()"
                        class="rounded-md border border-subtle bg-surface px-3 py-1.5 text-xs text-default hover:bg-surface-2"
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        [disabled]="!canSave()"
                        class="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-white hover:brightness-95 disabled:opacity-50"
                      >
                        {{ busy() ? 'Saving…' : editingId() ? 'Save changes' : 'Create reply' }}
                      </button>
                    </div>
                  }
                </div>
              </form>
            } @else {
              <div
                class="flex h-full flex-col items-center justify-center gap-2 py-8 text-center text-xs text-muted"
              >
                <lucide-icon name="zap" class="h-6 w-6 text-faint" />
                Pick a reply to edit it, or create a new one.
              </div>
            }
          </div>
        </div>
      </div>
    </div>
  `,
})
export class SavedRepliesManagerComponent implements OnInit {
  protected readonly store = inject(SavedRepliesStore);
  private readonly auth = inject(FurnitureAuthService);

  readonly dismissed = output<void>();

  protected readonly query = signal('');
  protected readonly formOpen = signal(false);
  protected readonly editingId = signal<string | null>(null);
  protected readonly editingAuthor = signal<string | null>(null);
  protected readonly title = signal('');
  protected readonly shortcut = signal('');
  protected readonly body = signal('');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly confirmingDelete = signal(false);

  private readonly canManageAll = this.auth.hasPermission('settings.conversations.manage');

  protected readonly filtered = computed(() => {
    const q = this.query().trim().toLowerCase();
    const rows = this.store.replies();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.title.toLowerCase().includes(q) ||
        r.body.toLowerCase().includes(q) ||
        (r.shortcut ?? '').includes(q),
    );
  });

  protected readonly canEditCurrent = computed(() => {
    if (!this.editingId()) return true;
    return this.canManageAll || this.editingAuthor() === this.auth.currentUserId();
  });

  protected readonly shortcutInvalid = computed(() => {
    const s = this.shortcut().trim();
    return s.length > 0 && !SHORTCUT_RE.test(s);
  });

  protected readonly canSave = computed(
    () =>
      !this.busy() &&
      this.title().trim().length > 0 &&
      this.body().trim().length > 0 &&
      !this.shortcutInvalid(),
  );

  ngOnInit(): void {
    this.store.ensureLoaded();
  }

  /** Open the form pre-filled with composer text ("Save as reply"). */
  public prefill(body: string): void {
    this.startCreate();
    this.body.set(body);
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    this.dismissed.emit();
  }

  protected startCreate(): void {
    this.editingId.set(null);
    this.editingAuthor.set(null);
    this.title.set('');
    this.shortcut.set('');
    this.body.set('');
    this.error.set(null);
    this.confirmingDelete.set(false);
    this.formOpen.set(true);
  }

  protected startEdit(r: SavedReply): void {
    this.editingId.set(r.id);
    this.editingAuthor.set(r.created_by_user_id);
    this.title.set(r.title);
    this.shortcut.set(r.shortcut ?? '');
    this.body.set(r.body);
    this.error.set(null);
    this.confirmingDelete.set(false);
    this.formOpen.set(true);
  }

  protected cancelForm(): void {
    this.formOpen.set(false);
    this.editingId.set(null);
    this.error.set(null);
  }

  protected save(): void {
    if (!this.canSave()) return;
    const input = {
      title: this.title().trim(),
      body: this.body().trim(),
      shortcut: this.shortcut().trim() || null,
    };
    const id = this.editingId();
    this.busy.set(true);
    this.error.set(null);
    const call = id ? this.store.update(id, input) : this.store.create(input);
    call.subscribe({
      next: (row) => {
        this.busy.set(false);
        this.startEdit(row);
      },
      error: (err: HttpErrorResponse) => {
        this.busy.set(false);
        this.error.set(extractApiError(err) ?? 'Could not save the reply.');
      },
    });
  }

  protected remove(): void {
    const id = this.editingId();
    if (!id) return;
    this.busy.set(true);
    this.store.remove(id).subscribe({
      next: () => {
        this.busy.set(false);
        this.cancelForm();
      },
      error: (err: HttpErrorResponse) => {
        this.busy.set(false);
        this.confirmingDelete.set(false);
        this.error.set(extractApiError(err) ?? 'Could not delete the reply.');
      },
    });
  }
}

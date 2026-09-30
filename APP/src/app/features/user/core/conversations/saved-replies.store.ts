import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';
import { ConversationsApiService, SavedReply, SavedReplyInput } from './conversations-api.service';

/**
 * Org-wide saved replies, shared by the composer's `/shortcut` picker,
 * the Saved-replies menu and the manager modal so a create / edit /
 * delete in one place is reflected everywhere without refetching.
 * Loaded lazily on first use.
 */
@Injectable({ providedIn: 'root' })
export class SavedRepliesStore {
  private readonly api = inject(ConversationsApiService);

  readonly replies = signal<SavedReply[]>([]);
  readonly loaded = signal(false);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);

  /** Fetch once; later calls are no-ops unless `force` is set. */
  ensureLoaded(force = false): void {
    if ((this.loaded() && !force) || this.loading()) return;
    this.loading.set(true);
    this.error.set(null);
    this.api.listSavedReplies().subscribe({
      next: (rows) => {
        this.replies.set(rows);
        this.loaded.set(true);
        this.loading.set(false);
      },
      error: (err: HttpErrorResponse) => {
        this.loading.set(false);
        this.error.set(extractApiError(err) ?? 'Could not load saved replies.');
      },
    });
  }

  create(input: SavedReplyInput): Observable<SavedReply> {
    return this.api
      .createSavedReply(input)
      .pipe(tap((row) => this.replies.update((rows) => sortByTitle([...rows, row]))));
  }

  update(id: string, input: SavedReplyInput): Observable<SavedReply> {
    return this.api
      .updateSavedReply(id, input)
      .pipe(
        tap((row) =>
          this.replies.update((rows) => sortByTitle(rows.map((r) => (r.id === id ? row : r)))),
        ),
      );
  }

  remove(id: string): Observable<void> {
    return this.api
      .deleteSavedReply(id)
      .pipe(tap(() => this.replies.update((rows) => rows.filter((r) => r.id !== id))));
  }

  /** Replies matching a composer query: shortcut prefix first, then
   *  title / body substring. */
  search(query: string, limit = 8): SavedReply[] {
    const q = query.trim().toLowerCase();
    const rows = this.replies();
    if (!q) return rows.slice(0, limit);
    const byShortcut = rows.filter((r) => r.shortcut?.startsWith(q));
    const rest = rows.filter(
      (r) =>
        !byShortcut.includes(r) &&
        (r.title.toLowerCase().includes(q) || r.body.toLowerCase().includes(q)),
    );
    return [...byShortcut, ...rest].slice(0, limit);
  }
}

function sortByTitle(rows: SavedReply[]): SavedReply[] {
  return [...rows].sort((a, b) => a.title.localeCompare(b.title));
}

/**
 * Contact groups list page — `/user/contacts/groups`.
 *
 * Owner / Sales Manager sees a table of saved audiences with:
 *   - Name + description
 *   - Mode pill (Dynamic / Static)
 *   - Member count (resolved live by backend on each list call)
 *   - Created date
 *   - Edit + Delete actions (delete confirms inline)
 *
 * Empty state explains the concept and links to the create form +
 * the XLSX import (Step 3.5.10) which also produces groups.
 *
 * Permission gating happens server-side; the page renders the
 * action buttons unconditionally and lets the API enforce.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { DatePipe } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  ContactGroup,
  ContactGroupsApiService,
} from './groups-api.service';


@Component({
  selector: 'app-contact-groups-list-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, RouterLink, DatePipe],
  templateUrl: './groups-list.page.html',
})
export class ContactGroupsListPageComponent {
  private readonly api = inject(ContactGroupsApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly groups = signal<ContactGroup[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  /** Pending-delete confirm — set to the group whose Delete button
   *  was clicked; Cancel/Confirm flips it back. Only one pending at
   *  a time. */
  protected readonly pendingDelete = signal<ContactGroup | null>(null);
  protected readonly deleting = signal(false);

  constructor() {
    this._refresh();
  }

  protected onEdit(group: ContactGroup): void {
    void this.router.navigate(['/user/contacts/groups', group.id, 'edit']);
  }

  protected onDeleteClick(group: ContactGroup): void {
    this.pendingDelete.set(group);
  }

  protected onCancelDelete(): void {
    this.pendingDelete.set(null);
  }

  protected onConfirmDelete(): void {
    const target = this.pendingDelete();
    if (!target || this.deleting()) return;
    this.deleting.set(true);
    this.api
      .delete(target.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleting.set(false);
          this.pendingDelete.set(null);
          // Optimistic update — remove the row locally instead of
          // re-fetching the whole list.
          this.groups.update((rows) =>
            rows.filter((r) => r.id !== target.id),
          );
        },
        error: (err: HttpErrorResponse) => {
          this.deleting.set(false);
          this.loadError.set(extractApiError(err));
        },
      });
  }

  private _refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (response) => {
          this.groups.set(response.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err));
        },
      });
  }
}

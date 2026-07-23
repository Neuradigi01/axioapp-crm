/**
 * Group create + edit page (`/user/contacts/groups/new` and
 * `/user/contacts/groups/:id/edit`).
 *
 * Two modes, set at creation and immutable thereafter:
 *
 *   Dynamic — filter inputs (q / source / tag); the group re-resolves
 *             at send time so new matching contacts auto-include.
 *   Static  — searchable contact picker; member set frozen at save.
 *
 * On create, the mode toggle is editable. On edit, the toggle is
 * disabled (backend rejects mode flips via `update_group`).
 *
 * Live audience-size preview: a debounced call to `/preview-size`
 * shows "X contacts match" as the operator types in dynamic mode
 * or as they pick contacts in static mode.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { Subject, of } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';
import { ContactListItem, ContactsApiService } from '../contacts-api.service';
import {
  ContactGroupCreate,
  ContactGroupUpdate,
  ContactGroupsApiService,
  GroupFilter,
} from './groups-api.service';

@Component({
  selector: 'app-contact-group-edit-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReactiveFormsModule, RouterLink],
  templateUrl: './group-edit.page.html',
})
export class ContactGroupEditPageComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(ContactGroupsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly groupId = signal<string | null>(null);
  protected readonly isEdit = computed(() => this.groupId() !== null);
  protected readonly loading = signal(false);
  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  // Mode toggle — editable on create, locked on edit.
  protected readonly mode = signal<'dynamic' | 'static'>('dynamic');

  // Live audience-size preview.
  protected readonly previewCount = signal<number | null>(null);
  protected readonly previewLoading = signal(false);
  private readonly previewTrigger$ = new Subject<void>();

  // Static-mode contact picker state.
  protected readonly searchResults = signal<ContactListItem[]>([]);
  protected readonly searchLoading = signal(false);
  protected readonly selectedContacts = signal<ContactListItem[]>([]);

  /** IDs of existing members that were loaded from the server but not
   *  hydrated into `selectedContacts` chips (i.e. members past the
   *  first 10 shown by name). These are preserved through save so the
   *  edit does not silently drop the tail. Mutated when the operator
   *  toggles a chip-visible existing member or explicitly clears all. */
  protected readonly hiddenExistingIds = signal<Set<string>>(new Set());

  protected readonly form = this.fb.group({
    name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    description: this.fb.control<string>('', { nonNullable: true }),
    filter_q: this.fb.control<string>('', { nonNullable: true }),
    filter_source: this.fb.control<string>('', { nonNullable: true }),
    filter_tag: this.fb.control<string>('', { nonNullable: true }),
    contact_search: this.fb.control<string>('', { nonNullable: true }),
  });

  constructor() {
    // Detect edit vs create from route param.
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.groupId.set(id);
      this._loadExisting(id);
    }

    // Live preview — debounced refresh on filter/picker change.
    this.previewTrigger$
      .pipe(
        debounceTime(300),
        switchMap(() => {
          if (this.mode() === 'dynamic') {
            const filter = this._currentFilter();
            // Only run preview if there's at least one filter set;
            // empty filter would resolve to "everyone" which is
            // expensive AND misleading on a fresh form.
            if (!filter.q && !filter.source && !filter.tag) {
              return of({ count: 0 });
            }
            this.previewLoading.set(true);
            return this.api
              .previewSize({ filter_json: filter })
              .pipe(catchError(() => of({ count: 0 })));
          }
          // Static mode — count is the selected list length.
          this.previewLoading.set(false);
          return of({ count: this.selectedContacts().length });
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(({ count }) => {
        this.previewCount.set(count);
        this.previewLoading.set(false);
      });

    // Re-preview whenever any filter / picker state changes.
    this.form.controls.filter_q.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.previewTrigger$.next());
    this.form.controls.filter_source.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.previewTrigger$.next());
    this.form.controls.filter_tag.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.previewTrigger$.next());

    // Contact search — debounced text → `/contacts?q=`.
    this.form.controls.contact_search.valueChanges
      .pipe(
        debounceTime(250),
        distinctUntilChanged(),
        switchMap((q) => {
          const term = (q || '').trim();
          if (!term || this.mode() !== 'static') {
            this.searchResults.set([]);
            return of(null);
          }
          this.searchLoading.set(true);
          return this.contactsApi
            .list({ q: term, page: 1, size: 20 })
            .pipe(catchError(() => of(null)));
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((response) => {
        this.searchLoading.set(false);
        if (response) {
          this.searchResults.set(response.items);
        }
      });

    // Mode flips clear preview + warn about cross-mode state loss.
    effect(() => {
      // tracks `mode()` signal
      this.mode();
      this.previewTrigger$.next();
    });
  }

  protected onModeChange(next: 'dynamic' | 'static'): void {
    if (this.isEdit()) return; // locked on edit
    this.mode.set(next);
  }

  protected onContactSelect(contact: ContactListItem): void {
    const current = this.selectedContacts();
    if (current.some((c) => c.id === contact.id)) return;
    this.selectedContacts.set([...current, contact]);
    this.form.controls.contact_search.setValue('');
    this.searchResults.set([]);
    this.previewTrigger$.next();
  }

  protected onContactRemove(contactId: string): void {
    this.selectedContacts.update((rows) => rows.filter((c) => c.id !== contactId));
    this.previewTrigger$.next();
  }

  protected save(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);

    const v = this.form.getRawValue();
    const isDynamic = this.mode() === 'dynamic';

    if (this.isEdit()) {
      const payload: ContactGroupUpdate = {
        name: v.name,
        description: v.description || null,
      };
      if (isDynamic) {
        payload.filter_json = this._currentFilter();
      } else {
        // Combine chip-visible ids with the hidden-but-preserved tail
        // of the original member set. Prevents the silent data-loss
        // bug where saving name-only changes on a >10-member static
        // group used to wipe the tail.
        const visible = this.selectedContacts().map((c) => c.id);
        const hidden = [...this.hiddenExistingIds()].filter((id) => !visible.includes(id));
        payload.contact_ids = [...visible, ...hidden];
      }
      this.api
        .update(this.groupId()!, payload)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: () => {
            this.submitting.set(false);
            void this.router.navigate(['/user/contacts/groups']);
          },
          error: (err: HttpErrorResponse) => {
            this.submitting.set(false);
            this.submitError.set(extractApiError(err));
          },
        });
      return;
    }

    const payload: ContactGroupCreate = {
      name: v.name,
      description: v.description || null,
      is_dynamic: isDynamic,
    };
    if (isDynamic) {
      payload.filter_json = this._currentFilter();
    } else {
      payload.contact_ids = this.selectedContacts().map((c) => c.id);
    }
    this.api
      .create(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.submitting.set(false);
          void this.router.navigate(['/user/contacts/groups']);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err));
        },
      });
  }

  private _currentFilter(): GroupFilter {
    const v = this.form.getRawValue();
    const out: GroupFilter = {};
    if (v.filter_q?.trim()) out.q = v.filter_q.trim();
    if (v.filter_source?.trim()) out.source = v.filter_source.trim();
    if (v.filter_tag?.trim()) out.tag = v.filter_tag.trim();
    return out;
  }

  private _loadExisting(id: string): void {
    this.loading.set(true);
    this.api
      .get(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (detail) => {
          this.mode.set(detail.is_dynamic ? 'dynamic' : 'static');
          this.form.patchValue({
            name: detail.name,
            description: detail.description ?? '',
            filter_q: detail.filter_json?.q ?? '',
            filter_source: detail.filter_json?.source ?? '',
            filter_tag: detail.filter_json?.tag ?? '',
          });
          this.previewCount.set(detail.member_count);

          if (detail.is_dynamic) {
            this.loading.set(false);
            return;
          }

          // Static group. Fetch the FULL member id list so a save
          // does not silently drop members past the first 10, then
          // hydrate real names for the sample (first 10) so the
          // chips are meaningful instead of "(existing member)".
          this._hydrateStaticMembers(id, detail.sample_contact_ids);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.submitError.set(extractApiError(err));
        },
      });
  }

  private _hydrateStaticMembers(groupId: string, sampleIds: string[]): void {
    this.api
      .listMemberIds(groupId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (allIds) => {
          const sampleSet = new Set(sampleIds);
          const hidden = new Set<string>(allIds.filter((id) => !sampleSet.has(id)));
          this.hiddenExistingIds.set(hidden);

          if (sampleIds.length === 0) {
            this.loading.set(false);
            return;
          }
          // Batched `POST /contacts/hydrate` — one round-trip for the
          // whole sample instead of N per-id GETs. Falls back to a
          // placeholder chip for any id that didn't come back (e.g.
          // deleted / anonymised).
          this.contactsApi
            .hydrateByIds(sampleIds)
            .pipe(
              catchError(() => of([] as ContactListItem[])),
              takeUntilDestroyed(this.destroyRef),
            )
            .subscribe((rows) => {
              const byId = new Map(rows.map((r) => [r.id, r]));
              const chips: ContactListItem[] = sampleIds.map((cid) => {
                const hydrated = byId.get(cid);
                if (hydrated) return hydrated;
                return {
                  id: cid,
                  full_name: 'Contact ' + cid.slice(0, 8),
                  phone: null,
                  email: null,
                } as ContactListItem;
              });
              this.selectedContacts.set(chips);
              this.loading.set(false);
            });
        },
        error: () => {
          // If the members fetch fails, fall back to placeholder chips
          // so the operator can at least edit metadata safely (they
          // still see the count from the detail response).
          const placeholders: ContactListItem[] = sampleIds.map(
            (cid) =>
              ({
                id: cid,
                full_name: 'Contact ' + cid.slice(0, 8),
                phone: null,
                email: null,
              }) as ContactListItem,
          );
          this.selectedContacts.set(placeholders);
          this.loading.set(false);
        },
      });
  }
}

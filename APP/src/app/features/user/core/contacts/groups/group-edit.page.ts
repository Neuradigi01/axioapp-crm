/**
 * Group create + edit page (`/user/contacts/groups/new` and
 * `/user/contacts/groups/:id/edit`).
 *
 * New groups are always static — a searchable contact picker whose
 * member set is frozen at save. The dynamic (filter-based) mode is
 * still hydrated on edit for legacy groups created before the UI
 * was simplified, but no new dynamic groups can be created.
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
import { catchError, debounceTime, switchMap } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';
import {
  ContactGroupCreate,
  ContactGroupUpdate,
  ContactGroupsApiService,
  GroupFilter,
} from './groups-api.service';
import { ContactPickerTableComponent } from './contact-picker-table.component';

@Component({
  selector: 'app-contact-group-edit-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReactiveFormsModule, RouterLink, ContactPickerTableComponent],
  templateUrl: './group-edit.page.html',
})
export class ContactGroupEditPageComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(ContactGroupsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly groupId = signal<string | null>(null);
  protected readonly isEdit = computed(() => this.groupId() !== null);
  protected readonly loading = signal(false);
  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  // New groups are always static. `mode` is only ever flipped to
  // `dynamic` when loading a legacy dynamic group on the edit route.
  protected readonly mode = signal<'dynamic' | 'static'>('static');

  // Live audience-size preview.
  protected readonly previewCount = signal<number | null>(null);
  protected readonly previewLoading = signal(false);
  private readonly previewTrigger$ = new Subject<void>();

  /** Two-way bound with the picker table. Seeded from
   *  `listMemberIds()` on edit; parent uses `.size` for the audience
   *  preview and passes `Array.from(...)` as `contact_ids` on save. */
  protected readonly selectedIds = signal<Set<string>>(new Set());

  protected readonly form = this.fb.group({
    name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    description: this.fb.control<string>('', { nonNullable: true }),
    filter_q: this.fb.control<string>('', { nonNullable: true }),
    filter_source: this.fb.control<string>('', { nonNullable: true }),
    filter_tag: this.fb.control<string>('', { nonNullable: true }),
  });

  constructor() {
    // Detect edit vs create from route param.
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.groupId.set(id);
      this._loadExisting(id);
    }

    // Live preview — debounced refresh for the dynamic-mode filter
    // inputs (legacy edit only). Static-mode preview is derived
    // directly from `selectedIds` via the effect below.
    this.previewTrigger$
      .pipe(
        debounceTime(300),
        switchMap(() => {
          if (this.mode() !== 'dynamic') return of(null);
          const filter = this._currentFilter();
          if (!filter.q && !filter.source && !filter.tag) {
            return of({ count: 0 });
          }
          this.previewLoading.set(true);
          return this.api
            .previewSize({ filter_json: filter })
            .pipe(catchError(() => of({ count: 0 })));
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((res) => {
        if (res === null) return;
        this.previewCount.set(res.count);
        this.previewLoading.set(false);
      });

    // Re-preview whenever any legacy dynamic filter changes.
    this.form.controls.filter_q.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.previewTrigger$.next());
    this.form.controls.filter_source.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.previewTrigger$.next());
    this.form.controls.filter_tag.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.previewTrigger$.next());

    // Static-mode preview: mirror the picker's selection count.
    effect(() => {
      if (this.mode() === 'static') {
        this.previewCount.set(this.selectedIds().size);
        this.previewLoading.set(false);
      }
    });
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
        payload.contact_ids = Array.from(this.selectedIds());
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
      payload.contact_ids = Array.from(this.selectedIds());
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

          // Static group. Fetch the full member id list and seed the
          // picker so its checkboxes render checked for every current
          // member. IDs (not full contact rows) is all the picker
          // needs — it hydrates row data itself per-page as the
          // operator paginates.
          this.api
            .listMemberIds(id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
              next: (allIds) => {
                this.selectedIds.set(new Set(allIds));
                this.loading.set(false);
              },
              error: () => {
                this.loading.set(false);
              },
            });
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.submitError.set(extractApiError(err));
        },
      });
  }
}

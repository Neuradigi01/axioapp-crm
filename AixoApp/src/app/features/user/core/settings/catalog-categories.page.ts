import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { nullableTrim } from '@core/services/form.util';

import { CatalogCategoriesApiService, CatalogCategory } from '../catalog/catalog-api.service';

/**
 * `/user/settings/catalog-categories` — CRUD list for the server-
 * managed catalog category taxonomy introduced in migration 0163.
 *
 * List renders inline (no drawer) with per-row Edit / Delete buttons.
 * "Add category" opens an inline form at the top of the table; edit
 * flips a row into inline-edit mode. Delete confirms via window.confirm
 * (matches the catalog page's approach).
 */
@Component({
  selector: 'app-catalog-categories-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule, RouterLink],
  templateUrl: './catalog-categories.page.html',
})
export class CatalogCategoriesPageComponent {
  private readonly api = inject(CatalogCategoriesApiService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly categories = signal<CatalogCategory[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saveError = signal<string | null>(null);
  protected readonly saving = signal(false);

  /** null = the "add category" form is closed. */
  protected readonly addingOpen = signal(false);
  /** category id currently being edited inline, or null. */
  protected readonly editingId = signal<string | null>(null);

  protected readonly form = this.fb.group({
    name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(64)],
    }),
    description: this.fb.control('', { nonNullable: true }),
    icon_emoji: this.fb.control('', { nonNullable: true, validators: [Validators.maxLength(8)] }),
    color_hex: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.pattern(/^#[0-9a-fA-F]{6}$/)],
    }),
    display_order: this.fb.control<number>(0, { nonNullable: true }),
    is_active: this.fb.control<boolean>(true, { nonNullable: true }),
  });

  protected readonly totalCategories = computed(() => this.categories().length);
  protected readonly activeCategories = computed(
    () => this.categories().filter((c) => c.is_active).length,
  );

  constructor() {
    this.reload();
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list(false)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.categories.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(extractApiError(err) ?? 'Could not load categories.');
          this.loading.set(false);
        },
      });
  }

  protected openAdd(): void {
    this.editingId.set(null);
    this.addingOpen.set(true);
    this.saveError.set(null);
    this.form.reset({
      name: '',
      description: '',
      icon_emoji: '',
      color_hex: '',
      display_order: this.categories().length,
      is_active: true,
    });
  }

  protected openEdit(cat: CatalogCategory): void {
    this.addingOpen.set(false);
    this.editingId.set(cat.id);
    this.saveError.set(null);
    this.form.reset({
      name: cat.name,
      description: cat.description ?? '',
      icon_emoji: cat.icon_emoji ?? '',
      color_hex: cat.color_hex ?? '',
      display_order: cat.display_order,
      is_active: cat.is_active,
    });
  }

  protected cancelForm(): void {
    this.addingOpen.set(false);
    this.editingId.set(null);
    this.saveError.set(null);
  }

  protected onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const raw = this.form.getRawValue();
    const payload = {
      name: raw.name.trim(),
      description: nullableTrim(raw.description),
      icon_emoji: nullableTrim(raw.icon_emoji),
      color_hex: nullableTrim(raw.color_hex),
      display_order: raw.display_order,
      is_active: raw.is_active,
    };

    this.saving.set(true);
    this.saveError.set(null);

    const editingId = this.editingId();
    if (editingId) {
      this.api
        .update(editingId, payload)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: () => {
            this.saving.set(false);
            this.cancelForm();
            this.reload();
          },
          error: (err: HttpErrorResponse) => {
            this.saving.set(false);
            this.saveError.set(this.errorMessage(err));
          },
        });
    } else {
      this.api
        .create(payload)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: () => {
            this.saving.set(false);
            this.cancelForm();
            this.reload();
          },
          error: (err: HttpErrorResponse) => {
            this.saving.set(false);
            this.saveError.set(this.errorMessage(err));
          },
        });
    }
  }

  protected onDelete(cat: CatalogCategory): void {
    const ok = window.confirm(`Delete category "${cat.name}"? This cannot be undone.`);
    if (!ok) return;
    const before = this.categories();
    this.categories.update((rows) => rows.filter((c) => c.id !== cat.id));
    this.api
      .delete(cat.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        error: (err: HttpErrorResponse) => {
          this.categories.set(before);
          this.loadError.set(extractApiError(err) ?? 'Could not delete category.');
        },
      });
  }

  private errorMessage(err: HttpErrorResponse): string {
    if (err.status === 409) return 'A category with that name already exists.';
    return extractApiError(err) ?? 'Could not save category.';
  }
}

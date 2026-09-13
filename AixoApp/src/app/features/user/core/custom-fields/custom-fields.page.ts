import { CdkDragDrop, DragDropModule, moveItemInArray } from '@angular/cdk/drag-drop';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { forkJoin } from 'rxjs';
import { LucideAngularModule } from 'lucide-angular';

import {
  CustomField,
  CustomFieldCreate,
  CustomFieldUpdate,
  CustomFieldsApiService,
  FieldSource,
} from './custom-fields-api.service';
import { FieldFormComponent } from './field-form.component';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Curated entity list for the picker. Each entry drives one card on
 * the entity selector at the top of the page — icon + label +
 * one-line description. Once the module registry exposes entity
 * discovery, this becomes ``registry.list().flatMap(m => m.entities)``.
 */
interface EntityDescriptor {
  value: string;
  label: string;
  icon: string;
  description: string;
}

const ENTITY_TYPES: ReadonlyArray<EntityDescriptor> = [
  {
    value: 'contact',
    label: 'Contacts',
    icon: 'users',
    description: 'People in your CRM',
  },
  {
    value: 'lead',
    label: 'Leads',
    icon: 'target',
    description: 'Sales opportunities',
  },
  {
    value: 'walk_in',
    label: 'Walk-ins',
    icon: 'footprints',
    description: 'In-store visits',
  },
  {
    value: 'appointment',
    label: 'Appointments',
    icon: 'calendar',
    description: 'Scheduled meetings',
  },
  {
    value: 'task',
    label: 'Tasks',
    icon: 'check-square',
    description: 'To-dos & follow-ups',
  },
  {
    value: 'catalog_item',
    label: 'Products',
    icon: 'package',
    description: 'Catalog items',
  },
];

@Component({
  selector: 'app-custom-fields-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DragDropModule, FieldFormComponent, LucideAngularModule],
  templateUrl: './custom-fields.page.html',
})
export class CustomFieldsPageComponent {
  private readonly api = inject(CustomFieldsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly entityTypes = ENTITY_TYPES;
  readonly entityType = signal<string>(ENTITY_TYPES[0].value);

  /** Metadata for the currently-selected entity card. Drives the
   *  section heading + description below the picker. */
  readonly selectedEntity = computed<EntityDescriptor>(
    () => ENTITY_TYPES.find((e) => e.value === this.entityType()) ?? ENTITY_TYPES[0],
  );

  readonly fields = signal<CustomField[]>([]);
  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);

  /** Form state: null = closed, undefined = open in create mode, value = edit mode. */
  readonly editing = signal<CustomField | null | undefined>(null);
  readonly formOpen = computed(() => this.editing() !== null);
  readonly editingField = computed(() => {
    const v = this.editing();
    return v === undefined ? null : (v ?? null);
  });
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);

  /** Delete-confirmation modal state. ``null`` = closed, a field = open
   *  with that row queued for deletion. Replaces ``window.confirm`` so
   *  the confirm dialog uses the app's own Tailwind styling
   *  (matches the merge-contact / delete-lead modals) instead of the
   *  browser's ugly native "localhost:4207 says" box. Source-aware
   *  copy — pack + system fields show an amber warning; user fields
   *  get the plain destructive confirm. */
  readonly pendingDelete = signal<CustomField | null>(null);
  readonly deleting = signal(false);

  constructor() {
    this.reload();
  }

  protected onEntityChange(value: string): void {
    this.entityType.set(value);
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list(this.entityType(), true)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.fields.set([...rows].sort((a, b) => a.display_order - b.display_order));
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.fields.set([]);
          this.loadError.set(extractApiError(err) ?? 'Failed to load fields.');
          this.loading.set(false);
        },
      });
  }

  protected openCreate(): void {
    this.formError.set(null);
    this.editing.set(undefined);
  }

  protected openEdit(field: CustomField): void {
    this.formError.set(null);
    this.editing.set(field);
  }

  protected closeForm(): void {
    this.editing.set(null);
    this.formError.set(null);
    this.submitting.set(false);
  }

  protected onSave(event: { create?: CustomFieldCreate; update?: CustomFieldUpdate }): void {
    if (event.create) {
      this.submitCreate(event.create);
    } else if (event.update) {
      const editing = this.editingField();
      if (editing) this.submitUpdate(editing.id, event.update);
    }
  }

  private submitCreate(payload: CustomFieldCreate): void {
    this.submitting.set(true);
    this.formError.set(null);
    this.api
      .create(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.fields.update((rows) =>
            [...rows, row].sort((a, b) => a.display_order - b.display_order),
          );
          this.submitting.set(false);
          this.closeForm();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.formError.set(extractApiError(err) ?? 'Could not create field.');
        },
      });
  }

  private submitUpdate(id: string, payload: CustomFieldUpdate): void {
    this.submitting.set(true);
    this.formError.set(null);
    this.api
      .update(id, payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.fields.update((rows) => rows.map((f) => (f.id === row.id ? row : f)));
          this.submitting.set(false);
          this.closeForm();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.formError.set(extractApiError(err) ?? 'Could not save field.');
        },
      });
  }

  /** Open the in-app delete-confirm modal. Actual delete fires from
   *  ``confirmDelete()`` when the operator hits the destructive
   *  button; ``cancelDelete()`` closes without touching anything. */
  protected onDelete(field: CustomField): void {
    this.pendingDelete.set(field);
  }

  protected cancelDelete(): void {
    if (this.deleting()) return;
    this.pendingDelete.set(null);
  }

  protected confirmDelete(): void {
    const field = this.pendingDelete();
    if (!field || this.deleting()) return;
    this.deleting.set(true);

    // Optimistic remove — restored on error like the original
    // ``window.confirm`` path did. Keeps the list snappy without
    // waiting for the API round-trip.
    const snapshot = this.fields();
    this.fields.update((rows) => rows.filter((f) => f.id !== field.id));

    this.api
      .delete(field.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleting.set(false);
          this.pendingDelete.set(null);
        },
        error: (err: HttpErrorResponse) => {
          // Revert + surface. Keep the modal open so the operator can
          // read the error against the field they were deleting.
          this.fields.set(snapshot);
          this.deleting.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not delete field.');
          this.pendingDelete.set(null);
        },
      });
  }

  protected onDrop(event: CdkDragDrop<CustomField[]>): void {
    if (event.previousIndex === event.currentIndex) return;
    const before = this.fields();
    const next = [...before];
    moveItemInArray(next, event.previousIndex, event.currentIndex);
    // Reassign display_order to mirror the new array index.
    const renumbered = next.map((f, i) => ({ ...f, display_order: i }));
    this.fields.set(renumbered);

    // Persist every field whose display_order actually changed.
    const updates = renumbered
      .filter((f, i) => before.find((b) => b.id === f.id)?.display_order !== i)
      .map((f) => this.api.update(f.id, { display_order: f.display_order }));
    if (updates.length === 0) return;

    forkJoin(updates)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        error: (err: HttpErrorResponse) => {
          // Revert the optimistic reorder.
          this.fields.set(before);
          this.loadError.set(extractApiError(err) ?? 'Could not reorder fields.');
        },
      });
  }

  protected badgeClass(source: FieldSource): string {
    switch (source) {
      case 'system':
        return 'bg-emerald-100 text-emerald-800 ring-emerald-200';
      case 'pack':
        return 'bg-sky-100 text-sky-800 ring-sky-200';
      case 'user':
        return 'bg-surface-2 text-default border-subtle';
    }
  }

  protected badgeLabel(source: FieldSource): string {
    switch (source) {
      case 'system':
        return 'System';
      case 'pack':
        return 'Pack';
      case 'user':
        return 'User';
    }
  }
}

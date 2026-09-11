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
import { HttpErrorResponse } from '@angular/common/http';

import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../../auth/auth.service';

import { StandardFieldsApiService } from '../../standard-fields/standard-fields-api.service';
import { StandardFieldsSignalsService } from '../../standard-fields/standard-fields-signals.service';
import type { StandardFieldEntity, StandardFieldRendered } from '../../standard-fields/types';
import {
  CORE_ENTITY_REGISTRY,
  EntityDescriptor,
  describeEntity,
} from '../../shared/entity-registry/entity-registry';

import { StandardFieldEditModalComponent } from './standard-field-edit-modal.component';

/**
 * Settings → Standard Fields tab.
 *
 *  - Fetches the entity list from the server (no hardcoded list — rule 5).
 *  - On selection, fetches the merged-defaults+overrides render.
 *  - Click [Edit] to open the edit modal; click [Reset] on overridden rows
 *    to clear the override row inline (no modal).
 *  - Subscribes to `StandardFieldsSignalsService.changedAt` so a save in
 *    the modal (or future cross-component edits) refreshes the table.
 */
@Component({
  selector: 'app-settings-standard-fields-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [StandardFieldEditModalComponent, LucideAngularModule],
  templateUrl: './standard-fields-tab.component.html',
})
export class StandardFieldsTabComponent {
  private readonly api = inject(StandardFieldsApiService);
  private readonly signals = inject(StandardFieldsSignalsService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly entities = signal<StandardFieldEntity[]>([]);
  protected readonly entity = signal<string>('');

  protected readonly fields = signal<StandardFieldRendered[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly resettingKey = signal<string | null>(null);

  /** Field currently being edited (drives the modal). null = closed. */
  protected readonly editing = signal<StandardFieldRendered | null>(null);

  readonly canManage = computed(() => this.auth.hasPermission('settings.standard_fields.manage'));

  constructor() {
    // Load the entity dropdown once on mount. Pick the first as default.
    this.api
      .entities()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.entities.set(resp.items);
          if (resp.items.length > 0 && !this.entity()) {
            this.entity.set(resp.items[0].entity);
          }
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Failed to load entities.');
        },
      });

    // Fetch the table whenever the entity changes or a save/reset fires.
    effect(() => {
      const e = this.entity();
      // Read the signal so this effect re-runs after saves/resets.
      this.signals.changedAt();
      if (!e) return;
      this.fetchFields(e);
    });
  }

  private fetchFields(entity: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .render(entity)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.fields.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.fields.set([]);
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Failed to load fields.');
        },
      });
  }

  /** Card-picker data — one entry per API-registered entity, ordered by
   *  the shared `CORE_ENTITY_REGISTRY` so the picker reads the same on
   *  Standard Fields as on Custom Fields. Unknown entities (future
   *  vertical packs that register a new one before the registry catches
   *  up) still render via `describeEntity`'s fallback. */
  protected readonly entityCards = computed<Array<EntityDescriptor & { fieldCount: number }>>(
    () => {
      const byValue = new Map(this.entities().map((e) => [e.entity, e.field_count]));
      const registered = CORE_ENTITY_REGISTRY.filter((d) => byValue.has(d.value)).map((d) => ({
        ...d,
        fieldCount: byValue.get(d.value) ?? 0,
      }));
      const known = new Set(registered.map((c) => c.value));
      const extras = this.entities()
        .filter((e) => !known.has(e.entity))
        .map((e) => ({ ...describeEntity(e.entity), fieldCount: e.field_count }));
      return [...registered, ...extras];
    },
  );

  /** Metadata for the currently-selected entity. Drives the section
   *  heading + description below the picker. */
  protected readonly selectedEntity = computed<EntityDescriptor>(() =>
    describeEntity(this.entity()),
  );

  protected onEntityChange(value: string): void {
    this.entity.set(value);
  }

  protected openEdit(field: StandardFieldRendered): void {
    this.editing.set(field);
  }

  protected closeModal(): void {
    this.editing.set(null);
  }

  protected onModalSaved(): void {
    this.editing.set(null);
    // The signals service already fired notifyChange() — the `effect`
    // above will refetch automatically.
  }

  protected onModalReset(): void {
    this.editing.set(null);
  }

  /** Inline reset (without opening the modal) for already-overridden rows. */
  protected resetRow(field: StandardFieldRendered): void {
    this.resettingKey.set(field.field_key);
    this.api.reset(field.entity, field.field_key).subscribe({
      next: () => {
        this.resettingKey.set(null);
        this.signals.notifyChange();
      },
      error: (err: HttpErrorResponse) => {
        this.resettingKey.set(null);
        this.error.set(extractApiError(err) ?? 'Reset failed.');
      },
    });
  }
}

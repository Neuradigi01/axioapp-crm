import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';

import { extractApiError } from '@core/services/api-error.util';

import { PipelineStage, PipelinesApiService, StageUpdate } from './pipelines-api.service';

/**
 * Reusable popover for editing a single pipeline stage: name, colour,
 * position, and delete. Self-contained — knows nothing about the
 * kanban that hosts it. Emits typed events:
 *
 *   - `saved`         after a successful PATCH
 *   - `deleted`       after a successful DELETE with no card conflict
 *   - `deleteBlocked` after DELETE returned 409 (parent opens the
 *                     relocation modal to collect a target and retry)
 *   - `closed`        on Cancel / outside-click
 *
 * Terminal stages (`is_won` / `is_lost`) hide the position buttons
 * and the delete link and surface a small notice — those invariants
 * are pack-owned; the API rejects the changes anyway.
 *
 * Permission gating is the parent's job. This popover is rendered
 * only when the caller has already decided `canManage()` is true.
 */
@Component({
  selector: 'app-stage-editor-popover',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  templateUrl: './stage-editor-popover.component.html',
})
export class StageEditorPopoverComponent {
  private readonly api = inject(PipelinesApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly stage = input.required<PipelineStage>();
  readonly pipelineKey = input.required<string>();
  readonly siblingCount = input<number>(0);

  readonly saved = output<PipelineStage>();
  readonly deleted = output<{ stageId: string }>();
  readonly deleteBlocked = output<{ stageId: string; cardsInStage: number }>();
  readonly closed = output<void>();

  /**
   * Six neutral-but-distinct presets sized for kanban column headers.
   * Free hex input lives beside the swatches for arbitrary brand colours.
   */
  protected readonly presetColors = [
    '#a855f7',
    '#3b82f6',
    '#10b981',
    '#f59e0b',
    '#ef4444',
    '#64748b',
  ];

  protected readonly nameValue = signal('');
  protected readonly colorValue = signal<string | null>(null);
  protected readonly displayOrderValue = signal(0);
  protected readonly saving = signal(false);
  protected readonly deleting = signal(false);
  protected readonly saveError = signal<string | null>(null);
  protected readonly deleteError = signal<string | null>(null);

  protected readonly isTerminal = computed(() => {
    const s = this.stage();
    return s.is_won || s.is_lost;
  });

  protected readonly nameTrimmed = computed(() => this.nameValue().trim());

  protected readonly nameValid = computed(() => {
    const n = this.nameTrimmed();
    return n.length >= 1 && n.length <= 128;
  });

  protected readonly colorValid = computed(() => {
    const c = this.colorValue();
    if (c == null || c === '') return true;
    return /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(c);
  });

  protected readonly dirty = computed(() => {
    const s = this.stage();
    return (
      this.nameTrimmed() !== s.name ||
      (this.colorValue() ?? null) !== (s.color ?? null) ||
      this.displayOrderValue() !== s.display_order
    );
  });

  protected readonly canSave = computed(
    () => this.dirty() && this.nameValid() && this.colorValid() && !this.saving(),
  );

  protected readonly canMoveLeft = computed(
    () => !this.isTerminal() && this.displayOrderValue() > 0,
  );

  protected readonly canMoveRight = computed(
    () => !this.isTerminal() && this.displayOrderValue() < Math.max(0, this.siblingCount() - 1),
  );

  constructor() {
    // Reset local state whenever the bound stage changes.
    effect(() => {
      const s = this.stage();
      this.nameValue.set(s.name);
      this.colorValue.set(s.color ?? null);
      this.displayOrderValue.set(s.display_order);
      this.saveError.set(null);
      this.deleteError.set(null);
    });
  }

  protected onNameInput(value: string): void {
    this.nameValue.set(value);
  }

  protected onSelectPreset(color: string): void {
    this.colorValue.set(color);
  }

  protected onColorInput(value: string): void {
    const trimmed = value.trim();
    this.colorValue.set(trimmed === '' ? null : trimmed);
  }

  protected onMoveLeft(): void {
    if (!this.canMoveLeft()) return;
    this.displayOrderValue.update((v) => Math.max(0, v - 1));
  }

  protected onMoveRight(): void {
    if (!this.canMoveRight()) return;
    const max = Math.max(0, this.siblingCount() - 1);
    this.displayOrderValue.update((v) => Math.min(max, v + 1));
  }

  protected onCancel(): void {
    this.closed.emit();
  }

  protected onSave(): void {
    if (!this.canSave()) return;
    const payload = this.buildPatchPayload();
    if (Object.keys(payload).length === 0) {
      this.closed.emit();
      return;
    }

    this.saving.set(true);
    this.saveError.set(null);

    this.api
      .updateStage(this.pipelineKey(), this.stage().id, payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.saving.set(false);
          this.saved.emit(updated);
          this.closed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.saveError.set(extractApiError(err) ?? 'Could not save stage.');
        },
      });
  }

  protected onDelete(): void {
    if (this.isTerminal() || this.deleting()) return;
    this.deleting.set(true);
    this.deleteError.set(null);

    const stageId = this.stage().id;
    this.api
      .deleteStage(this.pipelineKey(), stageId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleting.set(false);
          this.deleted.emit({ stageId });
          this.closed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.deleting.set(false);
          const cardsInStage = this.cardsInStageFromError(err);
          if (err.status === 409 && cardsInStage != null) {
            // Stage holds cards — parent opens the relocation modal.
            this.deleteBlocked.emit({ stageId, cardsInStage });
            return;
          }
          this.deleteError.set(extractApiError(err) ?? 'Could not delete stage.');
        },
      });
  }

  private buildPatchPayload(): StageUpdate {
    const s = this.stage();
    const payload: StageUpdate = {};
    if (this.nameTrimmed() !== s.name) {
      payload.name = this.nameTrimmed();
    }
    if ((this.colorValue() ?? null) !== (s.color ?? null)) {
      payload.color = this.colorValue();
    }
    if (this.displayOrderValue() !== s.display_order) {
      payload.display_order = this.displayOrderValue();
    }
    return payload;
  }

  private cardsInStageFromError(err: HttpErrorResponse): number | null {
    const detail = (err.error as { detail?: unknown })?.detail;
    if (detail && typeof detail === 'object') {
      const cards = (detail as { cards_in_stage?: unknown }).cards_in_stage;
      if (typeof cards === 'number') return cards;
    }
    return null;
  }
}

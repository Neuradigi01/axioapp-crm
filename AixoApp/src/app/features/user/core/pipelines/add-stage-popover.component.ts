import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';

import { extractApiError } from '@core/services/api-error.util';

import { PipelineStage, PipelinesApiService, StageCreate } from './pipelines-api.service';

/**
 * Reusable popover for adding a new pipeline stage. Self-contained,
 * mirrors the editor popover from Step 2:
 *
 *   - `created` after a successful POST returns the new stage row
 *   - `closed`  on Cancel
 *
 * The "Insert" dropdown surfaces only non-terminal stages from
 * `stages` (terminal stages always stay at the end, so anchoring
 * after them is UX nonsense even though the API would allow it).
 * `null` afterStageKey means "append at the end" — the request omits
 * `after_stage_key` entirely so the backend hits its append branch.
 *
 * Permission gating is the parent's job — this popover is rendered
 * only when the caller already decided `canManage()` is true.
 */
@Component({
  selector: 'app-add-stage-popover',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  templateUrl: './add-stage-popover.component.html',
})
export class AddStagePopoverComponent {
  private readonly api = inject(PipelinesApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly pipelineKey = input.required<string>();
  readonly stages = input.required<PipelineStage[]>();

  readonly created = output<PipelineStage>();
  readonly closed = output<void>();

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
  protected readonly afterStageKey = signal<string | null>(null);
  protected readonly submitting = signal(false);
  protected readonly nameError = signal<string | null>(null);
  protected readonly submitError = signal<string | null>(null);

  protected readonly anchorOptions = computed<PipelineStage[]>(() =>
    [...this.stages()]
      .filter((s) => !s.is_won && !s.is_lost)
      .sort((a, b) => a.display_order - b.display_order),
  );

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

  protected readonly canSubmit = computed(
    () => this.nameValid() && this.colorValid() && !this.submitting(),
  );

  protected onNameInput(value: string): void {
    this.nameValue.set(value);
    if (this.nameError()) this.nameError.set(null);
  }

  protected onSelectPreset(color: string): void {
    this.colorValue.set(color);
  }

  protected onColorInput(value: string): void {
    const trimmed = value.trim();
    this.colorValue.set(trimmed === '' ? null : trimmed);
  }

  protected onAnchorChange(value: string): void {
    this.afterStageKey.set(value === '' ? null : value);
  }

  protected onCancel(): void {
    this.closed.emit();
  }

  protected onSubmit(): void {
    if (!this.canSubmit()) return;

    const payload: StageCreate = { name: this.nameTrimmed() };
    const color = this.colorValue();
    if (color) payload.color = color;
    const anchor = this.afterStageKey();
    if (anchor) payload.after_stage_key = anchor;

    this.submitting.set(true);
    this.nameError.set(null);
    this.submitError.set(null);

    this.api
      .createStage(this.pipelineKey(), payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (stage) => {
          this.submitting.set(false);
          this.created.emit(stage);
          this.closed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          const msg = extractApiError(err);
          if (err.status === 422) {
            this.nameError.set(msg ?? 'Could not create stage.');
            return;
          }
          if (err.status === 403) {
            this.submitError.set("You don't have permission to add stages.");
            this.closed.emit();
            return;
          }
          this.submitError.set(msg ?? 'Could not create stage.');
        },
      });
  }
}

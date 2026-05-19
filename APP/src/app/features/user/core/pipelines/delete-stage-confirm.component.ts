import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { PipelineStage } from './pipelines-api.service';

/**
 * Centered modal that opens after DELETE returned 409 with
 * `cards_in_stage > 0`. Forces the admin to pick a relocation target
 * before re-invoking delete with `moveLeadsTo`.
 *
 * Default selection is the stage immediately before the one being
 * deleted by `display_order`; if the deleted stage was at slot 0, the
 * first candidate is chosen instead.
 */
@Component({
  selector: 'app-delete-stage-confirm',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  templateUrl: './delete-stage-confirm.component.html',
})
export class DeleteStageConfirmComponent {
  readonly stage = input.required<PipelineStage>();
  readonly cardsInStage = input.required<number>();
  readonly candidateStages = input.required<PipelineStage[]>();

  readonly confirmed = output<{ moveLeadsTo: string }>();
  readonly cancelled = output<void>();

  protected readonly orderedCandidates = computed<PipelineStage[]>(() =>
    [...this.candidateStages()].sort(
      (a, b) => a.display_order - b.display_order,
    ),
  );

  protected readonly moveLeadsTo = signal<string>('');

  protected readonly canConfirm = computed(() => this.moveLeadsTo() !== '');

  constructor() {
    // Pick the default target whenever the bound stage changes.
    effect(() => {
      const deleted = this.stage();
      const candidates = this.orderedCandidates();
      if (candidates.length === 0) {
        this.moveLeadsTo.set('');
        return;
      }
      const before = [...candidates]
        .reverse()
        .find((s) => s.display_order < deleted.display_order);
      this.moveLeadsTo.set((before ?? candidates[0]).key);
    });
  }

  protected onTargetChange(value: string): void {
    this.moveLeadsTo.set(value);
  }

  protected onConfirm(): void {
    if (!this.canConfirm()) return;
    this.confirmed.emit({ moveLeadsTo: this.moveLeadsTo() });
  }

  protected onCancel(): void {
    this.cancelled.emit();
  }
}

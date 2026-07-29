import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  TemplateRef,
  computed,
  contentChild,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { extractApiError } from '@core/services/api-error.util';

import {
  ItemMovedEvent,
  Pipeline,
  PipelineItem,
  PipelineStage,
  PipelinesApiService,
} from './pipelines-api.service';

/**
 * Table counterpart to `PipelineBoardComponent`. Same inputs and same
 * `itemMoved` output — the only difference is the visual: rows in a
 * table, with a per-row dropdown that changes the stage.
 *
 * Reusable: takes `pipelineKey` + caller-owned `items` + an optional
 * row-content `<ng-template>`. No Lead-specific styling here.
 */
@Component({
  selector: 'app-pipeline-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet],
  templateUrl: './pipeline-list.component.html',
})
export class PipelineListComponent {
  private readonly api = inject(PipelinesApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly pipelineKey = input.required<string>();
  readonly items = input<PipelineItem[]>([]);

  readonly itemMoved = output<ItemMovedEvent>();

  readonly itemTemplate = contentChild<TemplateRef<{ $implicit: PipelineItem }>>(TemplateRef);

  protected readonly pipeline = signal<Pipeline | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  readonly stages = computed<PipelineStage[]>(() => this.pipeline()?.stages ?? []);
  readonly stagesByKey = computed<Record<string, PipelineStage>>(() => {
    const out: Record<string, PipelineStage> = {};
    for (const s of this.stages()) out[s.key] = s;
    return out;
  });

  constructor() {
    effect(() => {
      const key = this.pipelineKey();
      if (!key) return;
      this.fetchPipeline(key);
    });
  }

  protected onStageChange(item: PipelineItem, event: Event): void {
    const target = event.target as HTMLSelectElement;
    const toStage = target.value;
    const fromStage = item.pipeline_stage;
    if (toStage === fromStage) return;
    this.itemMoved.emit({
      itemId: String(item.id),
      fromStage,
      toStage,
    });
  }

  protected stagePillStyle(stage: PipelineStage | undefined): Record<string, string> {
    if (!stage || !stage.color) return {};
    return { 'background-color': `${stage.color}22`, color: stage.color };
  }

  protected stageName(key: string): string {
    return this.stagesByKey()[key]?.name ?? key;
  }

  private fetchPipeline(key: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .getByKey(key)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (p) => {
          this.pipeline.set(p);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.pipeline.set(null);
          this.loadError.set(extractApiError(err) ?? `Could not load pipeline '${key}'.`);
          this.loading.set(false);
        },
      });
  }
}

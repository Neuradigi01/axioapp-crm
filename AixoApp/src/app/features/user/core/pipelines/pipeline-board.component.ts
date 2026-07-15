import {
  CdkDragDrop,
  DragDropModule,
  moveItemInArray,
  transferArrayItem,
} from '@angular/cdk/drag-drop';
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
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { extractApiError } from '@core/services/api-error.util';

import { FurnitureAuthService } from '../auth/auth.service';
import { AddStagePopoverComponent } from './add-stage-popover.component';
import { DeleteStageConfirmComponent } from './delete-stage-confirm.component';
import {
  ItemMovedEvent,
  Pipeline,
  PipelineItem,
  PipelineStage,
  PipelinesApiService,
} from './pipelines-api.service';
import { StageEditorPopoverComponent } from './stage-editor-popover.component';

/**
 * Reusable kanban board for any pipeline + item collection.
 *
 * Inputs:
 *   - `pipelineKey`: which pipeline to fetch from the API. The board
 *     loads stages on init (and on input change).
 *   - `items`: caller-owned array of items, each with at minimum
 *     `id` + `pipeline_stage`. Items are bucketed into stage columns
 *     by their `pipeline_stage` string.
 *
 * Output:
 *   - `itemMoved`: emitted whenever the user drags a card to a
 *     different column. The parent is expected to PATCH the moved
 *     item's stage on the server and (optimistically or otherwise)
 *     refresh the `items` input. The board does NOT call the move
 *     endpoint itself â€” that lives on the entity router (leads,
 *     custom_orders) which knows about `move_card`.
 *
 * Item rendering: caller supplies a `<ng-template>` child with an
 * `let-item` binding. The board passes each item through via
 * `*ngTemplateOutlet` so the caller can render any card layout they
 * want without the board knowing anything about contacts, leads, â€¦
 *
 * Note on cdk-drag-drop + signals: cdk mutates the drop-list's `data`
 * array in place to reflect the visual drop. We mirror items into a
 * local `buckets` signal that we mutate alongside cdk, and emit
 * `itemMoved` so the parent can persist. When the parent re-supplies
 * `items` the `effect` below rebuilds buckets from scratch.
 */
@Component({
  selector: 'app-pipeline-board',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DragDropModule,
    NgTemplateOutlet,
    StageEditorPopoverComponent,
    AddStagePopoverComponent,
    DeleteStageConfirmComponent,
  ],
  templateUrl: './pipeline-board.component.html',
})
export class PipelineBoardComponent {
  private readonly api = inject(PipelinesApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);

  readonly pipelineKey = input.required<string>();
  readonly items = input<PipelineItem[]>([]);

  readonly itemMoved = output<ItemMovedEvent>();

  readonly itemTemplate = contentChild<TemplateRef<{ $implicit: PipelineItem }>>(TemplateRef);

  protected readonly pipeline = signal<Pipeline | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  /** `{stageKey: PipelineItem[]}` â€” mutable so cdk-drag-drop works in place. */
  protected readonly buckets = signal<Record<string, PipelineItem[]>>({});

  readonly stages = computed<PipelineStage[]>(() => this.pipeline()?.stages ?? []);

  /** Admin-only management affordances live behind this gate. */
  protected readonly canManage = computed(() =>
    this.auth.currentPermissions().includes('pipelines.manage'),
  );

  protected readonly editingStage = signal<PipelineStage | null>(null);
  protected readonly addingPopoverOpen = signal(false);
  protected readonly deleteConfirm = signal<{
    stage: PipelineStage;
    cardsInStage: number;
  } | null>(null);
  protected readonly deleteError = signal<string | null>(null);

  protected readonly deleteCandidates = computed<PipelineStage[]>(() => {
    const confirmCtx = this.deleteConfirm();
    if (!confirmCtx) return [];
    return this.stages().filter((s) => s.id !== confirmCtx.stage.id);
  });

  /** Pre-built list of `cdkDropList` ids for `cdkDropListConnectedTo`. */
  readonly dropListIds = computed(() => this.stages().map((s) => this.dropListIdFor(s.key)));

  constructor() {
    // Re-fetch pipeline whenever the key changes.
    effect(() => {
      const key = this.pipelineKey();
      if (!key) return;
      this.fetchPipeline(key);
    });

    // Rebuild buckets from items + stages.
    effect(() => {
      const stages = this.stages();
      const items = this.items();
      untracked(() => this.rebuildBuckets(stages, items));
    });
  }

  protected onDrop(event: CdkDragDrop<PipelineItem[]>, toStage: string): void {
    if (event.previousContainer === event.container) {
      // Reorder within the same column â€” purely visual, no server call.
      moveItemInArray(event.container.data, event.previousIndex, event.currentIndex);
    } else {
      transferArrayItem(
        event.previousContainer.data,
        event.container.data,
        event.previousIndex,
        event.currentIndex,
      );
      const movedItem = event.container.data[event.currentIndex];
      const fromStage = this.stageKeyFromDropListId(event.previousContainer.id);
      this.itemMoved.emit({
        itemId: String(movedItem.id),
        fromStage,
        toStage,
      });
    }
    // Force the buckets signal to emit so any computed downstream
    // (count badges, "empty column" view) re-evaluates.
    this.buckets.update((b) => ({ ...b }));
  }

  protected bucket(key: string): PipelineItem[] {
    return this.buckets()[key] ?? [];
  }

  protected dropListIdFor(stageKey: string): string {
    return `pb-${this.pipelineKey()}-${stageKey}`;
  }

  protected colorBarStyle(stage: PipelineStage): Record<string, string> {
    return stage.color ? { 'background-color': stage.color } : { 'background-color': '#d4d4d8' };
  }

  protected stagePillClass(stage: PipelineStage): string {
    if (stage.is_won) return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
    if (stage.is_lost) return 'bg-red-100 text-red-700 ring-red-200';
    return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
  }

  private stageKeyFromDropListId(id: string): string {
    const prefix = `pb-${this.pipelineKey()}-`;
    return id.startsWith(prefix) ? id.slice(prefix.length) : id;
  }

  private rebuildBuckets(stages: PipelineStage[], items: PipelineItem[]): void {
    const next: Record<string, PipelineItem[]> = {};
    for (const stage of stages) next[stage.key] = [];
    for (const item of items) {
      const key = item.pipeline_stage;
      if (next[key]) next[key].push(item);
      else {
        // Item references an unknown stage â€” surface in a sentinel
        // bucket so the user still sees the item rather than losing it.
        // Won't render unless a column with this key exists, but the
        // emit-side won't see a phantom bucket either.
      }
    }
    this.buckets.set(next);
  }

  protected openEditor(stage: PipelineStage): void {
    if (!this.canManage()) return;
    this.editingStage.set(stage);
  }

  protected openAdd(): void {
    if (!this.canManage()) return;
    this.addingPopoverOpen.set(true);
  }

  protected onStageSaved(): void {
    this.fetchPipeline(this.pipelineKey());
    this.editingStage.set(null);
  }

  protected onStageDeleted(): void {
    this.fetchPipeline(this.pipelineKey());
    this.editingStage.set(null);
  }

  protected onDeleteBlocked(evt: { stageId: string; cardsInStage: number }): void {
    const stage = this.stages().find((s) => s.id === evt.stageId);
    if (!stage) return;
    this.deleteConfirm.set({ stage, cardsInStage: evt.cardsInStage });
    this.editingStage.set(null);
  }

  protected onEditorClosed(): void {
    this.editingStage.set(null);
  }

  protected onStageCreated(): void {
    this.fetchPipeline(this.pipelineKey());
    this.addingPopoverOpen.set(false);
  }

  protected onAddClosed(): void {
    this.addingPopoverOpen.set(false);
  }

  protected onDeleteConfirmed(evt: { moveLeadsTo: string }): void {
    const ctx = this.deleteConfirm();
    if (!ctx) return;
    this.deleteError.set(null);
    this.api
      .deleteStage(this.pipelineKey(), ctx.stage.id, evt.moveLeadsTo)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleteConfirm.set(null);
          this.fetchPipeline(this.pipelineKey());
        },
        error: (err: HttpErrorResponse) => {
          this.deleteError.set(extractApiError(err) ?? 'Could not delete stage.');
        },
      });
  }

  protected onDeleteCancelled(): void {
    this.deleteConfirm.set(null);
    this.deleteError.set(null);
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

import { JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, signal } from '@angular/core';

import { PipelineBoardComponent } from './pipeline-board.component';
import { PipelineListComponent } from './pipeline-list.component';
import { ItemMovedEvent, PipelineItem } from './pipelines-api.service';

/**
 * Storybook-style smoke route for the pipeline engine. Talks to the
 * real backend's `/pipelines/leads` endpoint (seeded in Step 2.9) and
 * uses an in-memory list of mock "lead" items as the cards. Reachable
 * only in dev builds via the `devRoutes` spread in `user.routes.ts`.
 */
interface MockLead extends PipelineItem {
  full_name: string;
  budget_inr: number;
}

const MOCK_ITEMS: ReadonlyArray<MockLead> = [
  { id: 'L-001', full_name: 'Asha Reddy', pipeline_stage: 'new', budget_inr: 80_000 },
  { id: 'L-002', full_name: 'Rohan Kapoor', pipeline_stage: 'new', budget_inr: 120_000 },
  { id: 'L-003', full_name: 'Priya Iyer', pipeline_stage: 'qualified', budget_inr: 200_000 },
  { id: 'L-004', full_name: 'Vikram Singh', pipeline_stage: 'qualified', budget_inr: 65_000 },
  { id: 'L-005', full_name: 'Meera Joshi', pipeline_stage: 'won', budget_inr: 175_000 },
];

@Component({
  selector: 'app-dev-pipeline-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [JsonPipe, PipelineBoardComponent, PipelineListComponent],
  templateUrl: './dev-pipeline.page.html',
})
export class DevPipelinePageComponent {
  protected readonly items = signal<MockLead[]>([...MOCK_ITEMS]);
  protected readonly view = signal<'board' | 'list'>('board');
  protected readonly lastEvent = signal<ItemMovedEvent | null>(null);

  protected setView(v: 'board' | 'list'): void {
    this.view.set(v);
  }

  protected onItemMoved(event: ItemMovedEvent): void {
    // In a real wire-up the parent would PATCH the server here.
    // For the demo we just mutate local state and surface the event.
    this.lastEvent.set(event);
    this.items.update((rows) =>
      rows.map((r) =>
        r.id === event.itemId ? { ...r, pipeline_stage: event.toStage } : r,
      ),
    );
  }

  protected formatInr(value: number): string {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(value);
  }
}

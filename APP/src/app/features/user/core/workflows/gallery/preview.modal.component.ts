import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { CanvasNode, CanvasStateService } from '../canvas/canvas-state.service';
import { WorkflowEdgeComponent } from '../canvas/edge.component';
import { NODE_HEIGHT, NODE_WIDTH, WorkflowNodeComponent } from '../canvas/node.component';
import { WorkflowGalleryEntry, WorkflowRead } from '../workflows-api.service';

/**
 * Read-only preview modal — renders the gallery entry's
 * `graph_preview` using the same SVG canvas components the editor
 * uses. The CanvasStateService is provided locally so the preview
 * state is isolated from any editor instance on the page; node-drag
 * + edge-drag handlers are deliberately not wired so the canvas
 * behaves as a static svg viewer.
 *
 * The "Use this template" CTA on the footer re-emits up to the
 * parent page, which then opens the clone-name modal.
 */

@Component({
  selector: 'app-gallery-preview-modal',
  standalone: true,
  imports: [CommonModule, LucideAngularModule, WorkflowNodeComponent, WorkflowEdgeComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [CanvasStateService],
  templateUrl: './preview.modal.component.html',
})
export class GalleryPreviewModalComponent {
  readonly entry = input.required<WorkflowGalleryEntry>();
  readonly close = output<void>();
  readonly use = output<void>();

  readonly state = inject(CanvasStateService);

  readonly nodeById = computed(() => {
    const m = new Map<string, CanvasNode>();
    for (const n of this.state.nodes()) {
      m.set(n.id, n);
    }
    return m;
  });

  readonly bounds = computed(() => {
    const nodes = this.state.nodes();
    if (nodes.length === 0) return { x: 0, y: 0, w: 1200, h: 800 };
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    for (const n of nodes) {
      const x = n.position?.x ?? 0;
      const y = n.position?.y ?? 0;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x + NODE_WIDTH);
      maxY = Math.max(maxY, y + NODE_HEIGHT);
    }
    const pad = 60;
    return {
      x: minX - pad,
      y: minY - pad,
      w: maxX - minX + pad * 2,
      h: maxY - minY + pad * 2,
    };
  });

  readonly viewBox = computed(() => {
    const b = this.bounds();
    return `${b.x} ${b.y} ${b.w} ${b.h}`;
  });

  constructor() {
    // Whenever the bound `entry` changes, load its graph into the
    // local CanvasStateService. Effect re-runs if the parent swaps
    // the input.
    effect(() => {
      const entry = this.entry();
      const synthetic: WorkflowRead = {
        id: entry.id,
        org_id: '',
        name: entry.name,
        description: entry.description,
        category: entry.category,
        folder_id: null,
        status: 'draft',
        current_version: 1,
        re_enrollment_rule: entry.re_enrollment_rule,
        is_marketing: entry.is_marketing,
        graph: entry.graph_preview,
        goal_node_id: null,
        cost_per_run_cents: 0,
        enabled_event_types: [],
        ab_sibling_id: null,
        created_at: '',
        updated_at: '',
      };
      this.state.load(synthetic);
    });
  }
}

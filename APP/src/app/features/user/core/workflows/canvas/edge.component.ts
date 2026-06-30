import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';

import { CanvasEdge, CanvasNode, CanvasStateService } from './canvas-state.service';
import { NODE_HEIGHT, NODE_WIDTH } from './node.component';
import { getNodeType } from './node-type-registry';

/**
 * SVG edge between two node ports.
 *
 * Cubic bezier — control points are offset vertically so edges curve
 * out of the source's bottom port and into the target's top port
 * without overlapping siblings. Labelled edges (yes / no / case-X /
 * event_received / timeout / a / b) render a mid-edge pill badge.
 *
 * Click → delete confirmation through `CanvasStateService.deleteEdge`.
 */

function outputPortX(index: number, total: number): number {
  if (total <= 1) return NODE_WIDTH / 2;
  const usable = NODE_WIDTH - 40;
  const step = usable / (total - 1);
  return 20 + step * index;
}

function buildPath(sx: number, sy: number, tx: number, ty: number): string {
  const dy = Math.max(60, Math.abs(ty - sy) * 0.5);
  return `M ${sx} ${sy} C ${sx} ${sy + dy}, ${tx} ${ty - dy}, ${tx} ${ty}`;
}

@Component({
  selector: '[appWorkflowEdge]',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg:g class="cursor-pointer" (click)="onClick($event)">
      <!-- Wide invisible hit-target so clicks land easily. -->
      <svg:path [attr.d]="path()" stroke="transparent" stroke-width="14" fill="none" />
      <svg:path
        [attr.d]="path()"
        [attr.stroke]="color()"
        stroke-width="2"
        fill="none"
        marker-end="url(#workflow-arrow)"
      />
      @if (edge().label) {
        <svg:foreignObject [attr.x]="midX() - 40" [attr.y]="midY() - 12" width="80" height="24">
          <div class="flex justify-center">
            <span
              class="px-2 py-0.5 rounded-full bg-white border border-zinc-300 text-[10px] text-zinc-700 shadow-sm"
            >
              {{ edge().label }}
            </span>
          </div>
        </svg:foreignObject>
      }
    </svg:g>
  `,
})
export class WorkflowEdgeComponent {
  readonly edge = input.required<CanvasEdge>();
  readonly source = input.required<CanvasNode>();
  readonly target = input.required<CanvasNode>();

  readonly deleted = output<string>();

  private readonly state = inject(CanvasStateService);

  // Source output-port position in graph coordinates.
  private readonly sourcePort = computed(() => {
    const node = this.source();
    const outputs = getNodeType(node.type)?.outputs ?? [];
    const idx = Math.max(
      0,
      outputs.findIndex((o) => (o.label ?? null) === (this.edge().label ?? null)),
    );
    const x = (node.position?.x ?? 0) + outputPortX(idx, outputs.length);
    const y = (node.position?.y ?? 0) + NODE_HEIGHT;
    return { x, y };
  });

  // Target input-port position in graph coordinates.
  private readonly targetPort = computed(() => {
    const node = this.target();
    return {
      x: (node.position?.x ?? 0) + NODE_WIDTH / 2,
      y: node.position?.y ?? 0,
    };
  });

  readonly path = computed(() => {
    const s = this.sourcePort();
    const t = this.targetPort();
    return buildPath(s.x, s.y, t.x, t.y);
  });

  readonly midX = computed(() => {
    const s = this.sourcePort();
    const t = this.targetPort();
    return (s.x + t.x) / 2;
  });

  readonly midY = computed(() => {
    const s = this.sourcePort();
    const t = this.targetPort();
    return (s.y + t.y) / 2;
  });

  readonly color = computed(() => {
    const lbl = this.edge().label;
    if (lbl === 'yes' || lbl === 'a' || lbl === 'event_received') {
      return 'rgb(16 185 129)'; // emerald-500
    }
    if (lbl === 'no' || lbl === 'b' || lbl === 'timeout') {
      return 'rgb(244 114 182)'; // pink-400
    }
    return 'rgb(148 163 184)'; // slate-400
  });

  onClick(event: MouseEvent): void {
    event.stopPropagation();
    if (confirm('Delete this edge?')) {
      const id = this.edge().id;
      this.state.deleteEdge(id);
      this.deleted.emit(id);
    }
  }
}

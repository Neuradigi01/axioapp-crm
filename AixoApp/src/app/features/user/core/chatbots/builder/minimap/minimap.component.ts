import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Output,
  computed,
  inject,
} from '@angular/core';

import { CanvasStateService } from '../canvas-state.service';

/**
 * Canvas minimap — bottom-left floating thumbnail of the whole bot
 * graph. Reads the existing ``CanvasStateService`` signals (nodes /
 * edges / trigger position / card width); never writes back. Emits
 * ``(jumpTo)`` with a node id when the operator clicks a rectangle
 * so the parent can smooth-scroll the canvas.
 *
 * Pure SVG — no canvas, no third-party lib. Bounding box + linear
 * scale is enough for a 100-node graph.
 */
@Component({
  selector: 'app-chatbot-minimap',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="fixed z-30 bottom-6 left-20 rounded-lg bg-surface/95 backdrop-blur border border-subtle shadow-xl overflow-hidden"
      [style.width.px]="MAP_W"
      [style.height.px]="MAP_H + 18"
      (click)="$event.stopPropagation()"
    >
      <div
        class="flex items-center justify-between px-2 py-1 border-b border-subtle text-[10px] font-semibold uppercase tracking-wider text-muted"
      >
        <span>Minimap</span>
        <span>{{ canvas.nodes().length }} nodes</span>
      </div>
      <svg
        [attr.width]="MAP_W"
        [attr.height]="MAP_H"
        class="block bg-app/40"
        (click)="onMapClick($event)"
      >
        <!-- Trigger rectangle -->
        <rect
          [attr.x]="trigger().x"
          [attr.y]="trigger().y"
          [attr.width]="trigger().w"
          [attr.height]="trigger().h"
          rx="1.5"
          class="fill-accent"
          opacity="0.85"
        />
        <!-- Nodes -->
        @for (r of nodeRects(); track r.id) {
          <rect
            [attr.x]="r.x"
            [attr.y]="r.y"
            [attr.width]="r.w"
            [attr.height]="r.h"
            rx="1.5"
            (click)="onNodeClick(r.id, $event)"
            [class]="
              r.id === canvas.selectedNodeId()
                ? 'fill-accent cursor-pointer'
                : 'fill-default/40 hover:fill-default/70 cursor-pointer'
            "
          />
        }
      </svg>
    </div>
  `,
})
export class ChatbotMinimapComponent {
  readonly canvas = inject(CanvasStateService);

  readonly MAP_W = 200;
  readonly MAP_H = 130;
  private readonly PAD = 6;

  @Output() readonly jumpTo = new EventEmitter<string>();

  /** Bounding box of everything on the canvas — trigger + all nodes
   *  — in canvas coordinates. Used to compute the linear scale that
   *  fits everything into the minimap. */
  private readonly bounds = computed(() => {
    const CANVAS_PAD = 24;
    const TRIGGER_GAP = 60;
    const CARD_HEIGHT = 320;
    const cardW = this.canvas.cardWidth();
    const nodeLeft = CANVAS_PAD + cardW + TRIGGER_GAP;
    const tp = this.canvas.triggerPosition();

    let minX = CANVAS_PAD + tp.x;
    let minY = CANVAS_PAD + tp.y;
    let maxX = minX + cardW;
    let maxY = minY + 118;
    for (const n of this.canvas.nodes()) {
      const nx = nodeLeft + n.position.x;
      const ny = n.position.y;
      minX = Math.min(minX, nx);
      minY = Math.min(minY, ny);
      maxX = Math.max(maxX, nx + cardW);
      maxY = Math.max(maxY, ny + CARD_HEIGHT);
    }
    return { minX, minY, maxX, maxY };
  });

  /** Linear scale factor: fit the bounding box into (MAP_W - 2*PAD,
   *  MAP_H - 2*PAD). Same scale on X and Y so the aspect stays true. */
  private readonly scale = computed(() => {
    const b = this.bounds();
    const w = b.maxX - b.minX || 1;
    const h = b.maxY - b.minY || 1;
    return Math.min((this.MAP_W - this.PAD * 2) / w, (this.MAP_H - this.PAD * 2) / h);
  });

  readonly trigger = computed(() => {
    const b = this.bounds();
    const s = this.scale();
    const cardW = this.canvas.cardWidth();
    const tp = this.canvas.triggerPosition();
    return {
      x: this.PAD + (24 + tp.x - b.minX) * s,
      y: this.PAD + (24 + tp.y - b.minY) * s,
      w: Math.max(4, cardW * s),
      h: Math.max(3, 118 * s),
    };
  });

  readonly nodeRects = computed(() => {
    const b = this.bounds();
    const s = this.scale();
    const cardW = this.canvas.cardWidth();
    const nodeLeft = 24 + cardW + 60;
    const CARD_HEIGHT = 320;
    return this.canvas.nodes().map((n) => ({
      id: n.id,
      x: this.PAD + (nodeLeft + n.position.x - b.minX) * s,
      y: this.PAD + (n.position.y - b.minY) * s,
      w: Math.max(4, cardW * s),
      h: Math.max(3, CARD_HEIGHT * s),
    }));
  });

  onNodeClick(id: string, evt: MouseEvent): void {
    evt.stopPropagation();
    this.jumpTo.emit(id);
  }

  /** Empty-map click: pick the nearest node to the click point so
   *  the operator can approximately steer the canvas even without
   *  hitting a rectangle exactly. */
  onMapClick(evt: MouseEvent): void {
    const target = evt.currentTarget as SVGSVGElement;
    const rect = target.getBoundingClientRect();
    const cx = evt.clientX - rect.left;
    const cy = evt.clientY - rect.top;
    let nearestId: string | null = null;
    let nearestDist = Infinity;
    for (const r of this.nodeRects()) {
      const dx = r.x + r.w / 2 - cx;
      const dy = r.y + r.h / 2 - cy;
      const d = dx * dx + dy * dy;
      if (d < nearestDist) {
        nearestDist = d;
        nearestId = r.id;
      }
    }
    if (nearestId) this.jumpTo.emit(nearestId);
  }
}

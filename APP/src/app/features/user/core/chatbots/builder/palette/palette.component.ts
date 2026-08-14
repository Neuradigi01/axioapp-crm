import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { CanvasStateService } from '../canvas-state.service';
import { NODE_TYPES, NodeTypeMeta, PaletteTab } from '../node-type-registry';

/**
 * Left-rail palette (tasks/chatbot-builder Step 13 / mockup.html).
 *
 * Pabbly-style: two tabs (Messages / Actions) with grid tiles. On
 * click, the tile emits `(add)` with the node meta — the parent
 * (builder.page) picks the drop position and calls
 * `canvasState.addNode(meta, pos)`.
 */
@Component({
  selector: 'app-chatbot-palette',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './palette.component.html',
})
export class ChatbotPaletteComponent {
  readonly canvas = inject(CanvasStateService);

  readonly tab = signal<PaletteTab>('messages');
  readonly search = signal<string>('');

  readonly filteredTiles = computed(() => {
    const t = this.tab();
    const term = this.search().trim().toLowerCase();
    let rows: NodeTypeMeta[] = NODE_TYPES.filter((n) => n.paletteTab === t);
    if (term) {
      rows = rows.filter((n) => n.label.toLowerCase().includes(term) || n.type.includes(term));
    }
    return rows;
  });

  @Output() add = new EventEmitter<NodeTypeMeta>();

  onTile(meta: NodeTypeMeta): void {
    this.add.emit(meta);
    // Also drop the node directly at a safe canvas coord so the
    // click-to-add UX works without a drag. Parent listens for
    // `add` for its own bookkeeping.
    this.canvas.addNode(meta, this.nextDropPosition());
  }

  /** Active resize gesture, if any — the width-drag handle records
   *  the mouse start-X + current palette width, then the document
   *  mousemove listener updates the width until mouseup. */
  private resizeStart: { startX: number; startWidth: number } | null = null;

  onResizeMouseDown(evt: MouseEvent): void {
    if (evt.button !== 0) return;
    evt.preventDefault();
    this.resizeStart = {
      startX: evt.clientX,
      startWidth: this.canvas.paletteWidth(),
    };
  }

  @HostListener('document:mousemove', ['$event'])
  onDocumentMouseMove(evt: MouseEvent): void {
    if (!this.resizeStart) return;
    const dx = evt.clientX - this.resizeStart.startX;
    this.canvas.setPaletteWidth(this.resizeStart.startWidth + dx);
  }

  @HostListener('document:mouseup')
  onDocumentMouseUp(): void {
    this.resizeStart = null;
  }

  private nextDropPosition(): { x: number; y: number } {
    // Cards are 320px wide × ~260px tall on average. A 30px cascade
    // (the original v1) stacks them almost on top of each other; a
    // proper flow reads top-to-bottom in a single column so operators
    // don't have to hunt for the last-added node.
    //
    // Strategy: drop each new node directly below the last one in a
    // column, snapping y to 240px increments. `updateNodePosition`
    // takes over once the operator drags a card manually.
    const existing = this.canvas.nodes();
    if (!existing.length) return { x: 0, y: 0 };
    const lastY = Math.max(...existing.map((n) => n.position.y));
    return { x: 0, y: lastY + 240 };
  }
}

import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
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
  private readonly canvas = inject(CanvasStateService);

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

  private nextDropPosition(): { x: number; y: number } {
    const existing = this.canvas.nodes();
    // Cascade successive drops so they don't stack on top of each
    // other. The builder canvas is CSS-positioned; nodes are
    // ~320px wide (mockup.html width), so 30px offsets stay
    // visible.
    const offset = existing.length * 30;
    return { x: 100 + offset, y: 100 + offset };
  }
}

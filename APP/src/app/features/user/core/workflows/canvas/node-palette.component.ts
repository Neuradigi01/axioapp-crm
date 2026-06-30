import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import {
  NODE_TYPES,
  PALETTE_SECTIONS,
  WorkflowNodeCategory,
  WorkflowNodeType,
} from './node-type-registry';


/**
 * Left-rail palette. Sections for triggers / send / record / routing /
 * tag-lifecycle / flow-control. Each row is a draggable item — drag
 * starts with a `text/workflow-node-type` MIME payload so the canvas
 * `drop` handler can introspect what was dropped.
 *
 * A small search box at the top filters across all categories — the
 * 42-item list isn't huge but the filter helps once operators learn
 * the type names by heart.
 */


@Component({
  selector: 'app-node-palette',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './node-palette.component.html',
})
export class NodePaletteComponent {
  readonly query = signal('');

  readonly sections = PALETTE_SECTIONS;

  readonly itemsByCategory = computed<
    Record<WorkflowNodeCategory, WorkflowNodeType[]>
  >(() => {
    const q = this.query().trim().toLowerCase();
    const filtered = q
      ? NODE_TYPES.filter(
          (n) =>
            n.label.toLowerCase().includes(q) ||
            n.type.toLowerCase().includes(q) ||
            n.description.toLowerCase().includes(q),
        )
      : NODE_TYPES;
    const out = {
      trigger: [],
      send: [],
      record: [],
      routing: [],
      tag_lifecycle: [],
      flow_control: [],
    } as Record<WorkflowNodeCategory, WorkflowNodeType[]>;
    for (const item of filtered) {
      out[item.category].push(item);
    }
    return out;
  });

  onDragStart(event: DragEvent, type: WorkflowNodeType): void {
    if (!event.dataTransfer) return;
    event.dataTransfer.effectAllowed = 'copy';
    event.dataTransfer.setData('text/workflow-node-type', type.type);
    // Also write `text/plain` so dropping outside the canvas (e.g. into a
    // text editor for inspection) doesn't drop a blob.
    event.dataTransfer.setData('text/plain', type.label);
  }
}

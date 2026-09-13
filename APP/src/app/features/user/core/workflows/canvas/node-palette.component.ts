import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, output, signal } from '@angular/core';
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

/** Per-category accent classes — surfaces the node's semantic role at
 *  a glance (triggers=amber, send=sky, record=emerald, routing=violet,
 *  tagging/lifecycle=rose, flow-control=slate). Kept in the component
 *  (not the registry) so the registry stays styling-free. */
interface CategoryAccent {
  /** Section-header dot. */
  dot: string;
  /** Icon chip bg + text + ring. */
  chip: string;
  /** Left border tint on the palette card. */
  border: string;
  /** Hover background tint on the palette card. */
  hoverBg: string;
}

const CATEGORY_ACCENT: Record<WorkflowNodeCategory, CategoryAccent> = {
  trigger: {
    dot: 'bg-amber-500',
    chip: 'bg-amber-500/10 text-amber-600 ring-amber-500/20',
    border: 'border-l-amber-500/40',
    hoverBg: 'hover:bg-amber-500/5',
  },
  send: {
    dot: 'bg-sky-500',
    chip: 'bg-sky-500/10 text-sky-600 ring-sky-500/20',
    border: 'border-l-sky-500/40',
    hoverBg: 'hover:bg-sky-500/5',
  },
  record: {
    dot: 'bg-emerald-500',
    chip: 'bg-emerald-500/10 text-emerald-600 ring-emerald-500/20',
    border: 'border-l-emerald-500/40',
    hoverBg: 'hover:bg-emerald-500/5',
  },
  routing: {
    dot: 'bg-violet-500',
    chip: 'bg-violet-500/10 text-violet-600 ring-violet-500/20',
    border: 'border-l-violet-500/40',
    hoverBg: 'hover:bg-violet-500/5',
  },
  tag_lifecycle: {
    dot: 'bg-rose-500',
    chip: 'bg-rose-500/10 text-rose-600 ring-rose-500/20',
    border: 'border-l-rose-500/40',
    hoverBg: 'hover:bg-rose-500/5',
  },
  flow_control: {
    dot: 'bg-slate-500',
    chip: 'bg-slate-500/10 text-slate-600 ring-slate-500/20',
    border: 'border-l-slate-500/40',
    hoverBg: 'hover:bg-slate-500/5',
  },
};

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

  /** Template helper — accent class strings for a given category. */
  protected accentFor(key: WorkflowNodeCategory): CategoryAccent {
    return CATEGORY_ACCENT[key];
  }

  /** Fires when the user taps a palette item (touch / accessibility
   *  fallback for the HTML5 drag/drop, which is mouse-only). The
   *  parent canvas adds the node at the current viewport centre. */
  readonly nodeAdded = output<string>();

  readonly itemsByCategory = computed<Record<WorkflowNodeCategory, WorkflowNodeType[]>>(() => {
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

  /** Tap fallback: touch devices can't fire drag events, so tapping a
   *  palette row asks the canvas to add the node at the viewport centre. */
  onTap(type: WorkflowNodeType): void {
    this.nodeAdded.emit(type.type);
  }
}

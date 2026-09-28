import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { CanvasNode } from './canvas-state.service';
import { getNodeType, WorkflowNodeCategory, WorkflowNodeType } from './node-type-registry';

/** Per-category SVG-safe styling for the node card — Tailwind's
 *  `fill-*` / `stroke-*` utilities so the same class strings work
 *  inside `<svg:rect>` markup. Kept in lockstep with the palette
 *  component's `CATEGORY_ACCENT` map so the palette-to-canvas
 *  transition reads as one visual system (triggers=amber,
 *  send=sky, record=emerald, routing=violet, tagging/lifecycle=rose,
 *  flow-control=slate). */
interface CanvasNodeStyle {
  /** Left-edge accent bar fill (solid category colour). */
  accent: string;
  /** Header strip fill (light tint of category colour). */
  headerTint: string;
  /** Node card outline stroke. */
  bodyStroke: string;
  /** Header icon colour (Tailwind text-* — foreignObject renders HTML). */
  iconColor: string;
}

const CANVAS_NODE_STYLE: Record<WorkflowNodeCategory, CanvasNodeStyle> = {
  trigger: {
    accent: 'fill-amber-500',
    headerTint: 'fill-amber-100',
    bodyStroke: 'stroke-amber-400',
    iconColor: 'text-amber-600',
  },
  send: {
    accent: 'fill-sky-500',
    headerTint: 'fill-sky-100',
    bodyStroke: 'stroke-sky-400',
    iconColor: 'text-sky-600',
  },
  record: {
    accent: 'fill-emerald-500',
    headerTint: 'fill-emerald-100',
    bodyStroke: 'stroke-emerald-400',
    iconColor: 'text-emerald-600',
  },
  routing: {
    accent: 'fill-violet-500',
    headerTint: 'fill-violet-100',
    bodyStroke: 'stroke-violet-400',
    iconColor: 'text-violet-600',
  },
  tag_lifecycle: {
    accent: 'fill-rose-500',
    headerTint: 'fill-rose-100',
    bodyStroke: 'stroke-rose-400',
    iconColor: 'text-rose-600',
  },
  flow_control: {
    accent: 'fill-slate-500',
    headerTint: 'fill-slate-100',
    bodyStroke: 'stroke-slate-400',
    iconColor: 'text-slate-600',
  },
};

const DEFAULT_NODE_STYLE: CanvasNodeStyle = CANVAS_NODE_STYLE.flow_control;

/**
 * Single canvas node — type-agnostic. Renders the rounded card with
 * input port (top edge) and output ports (bottom edge). Click → select;
 * drag → move. Right-click (or the top-right kebab) raises a
 * `nodeContextMenu` event; the canvas page owns the actual
 * Edit / Duplicate / Copy / Disconnect / Delete menu so it renders in
 * screen space rather than inside the zoom/pan SVG group.
 *
 * Pure presentation — every mutation routes through the canvas page /
 * `CanvasStateService` so undo / redo / dirty / auto-save stay in sync.
 *
 * Edge-creation drag starts from an output port (pointerdown on a port)
 * — the canvas page listens for `outputPortDown`, tracks the pending
 * edge, and on release hit-tests for a `[data-wf-node-id]` card (only
 * nodes with an input port carry the attribute).
 *
 * Validation marker: small red dot in the corner when
 * `node.config.__valid === false`. Step 15's node editor sets this
 * when required fields are missing.
 */

export const NODE_WIDTH = 220;
export const NODE_HEIGHT = 110;
export const NODE_HEADER = 30;

@Component({
  selector: '[appWorkflowNode]',
  standalone: true,
  imports: [CommonModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg:g
      [attr.transform]="transform()"
      [attr.data-wf-node-id]="hasInputPort() ? node().id : null"
      class="select-none"
      (pointerdown)="onCardPointerDown($event)"
      (click)="onCardClick($event)"
      (contextmenu)="onCardContextMenu($event)"
    >
      @if (selected()) {
        <svg:rect
          x="-4"
          y="-4"
          [attr.width]="WIDTH + 8"
          [attr.height]="HEIGHT + 8"
          rx="14"
          ry="14"
          fill="none"
          stroke="rgb(99 102 241)"
          stroke-width="2"
          stroke-dasharray="6 3"
        />
      }

      <!-- Card body: white fill + category-tinted outline. -->
      <svg:rect
        [attr.width]="WIDTH"
        [attr.height]="HEIGHT"
        rx="10"
        ry="10"
        [class]="'fill-white ' + style().bodyStroke"
        stroke-width="1.5"
      />

      <!-- Header strip — tinted with the category colour so the
           group is legible at a glance without opening the node. -->
      <svg:path [attr.d]="headerPath()" [class]="style().headerTint + ' stroke-transparent'" />
      <svg:rect [attr.width]="WIDTH" height="1" [attr.y]="HEADER" class="fill-zinc-200" />

      <!-- Left accent bar — solid group colour, anchors the card to
           its palette section. -->
      <svg:path [attr.d]="accentPath()" [class]="style().accent + ' stroke-transparent'" />

      <svg:foreignObject [attr.width]="WIDTH" [attr.height]="HEADER" x="0" y="0">
        <div class="flex items-center gap-2 px-3 h-full text-xs font-semibold text-zinc-900">
          <lucide-icon [name]="icon()" [class]="'w-3.5 h-3.5 ' + style().iconColor"></lucide-icon>
          <span class="truncate flex-1">{{ displayName() }}</span>
          @if (validationFailed()) {
            <span
              title="Configuration incomplete"
              class="inline-block w-2 h-2 rounded-full bg-red-500 shrink-0"
            ></span>
          }
        </div>
      </svg:foreignObject>

      <svg:foreignObject
        [attr.width]="WIDTH"
        [attr.height]="HEIGHT - HEADER - 4"
        x="0"
        [attr.y]="HEADER + 4"
      >
        <div class="px-3 text-[11px] leading-snug text-zinc-600">
          {{ description() }}
        </div>
      </svg:foreignObject>

      <svg:foreignObject [attr.x]="WIDTH - 26" y="6" width="20" height="20">
        <button
          type="button"
          class="w-5 h-5 flex items-center justify-center rounded text-zinc-400 hover:text-zinc-700 hover:bg-black/5"
          (click)="onMenuClick($event)"
          (pointerdown)="$event.stopPropagation()"
          aria-label="Node actions"
        >
          <lucide-icon name="more-vertical" class="w-3.5 h-3.5"></lucide-icon>
        </button>
      </svg:foreignObject>

      @if (hasInputPort()) {
        <svg:circle
          [attr.cx]="WIDTH / 2"
          cy="0"
          r="6"
          class="fill-white stroke-zinc-400 stroke-2"
          (pointerdown)="$event.stopPropagation()"
        />
      }

      @for (port of outputs(); track port.label || $index; let i = $index) {
        <svg:g
          [attr.transform]="'translate(' + outputPortX(i, outputs().length) + ',' + HEIGHT + ')'"
          class="cursor-crosshair"
          (pointerdown)="onOutputDown($event, port.label)"
        >
          <!-- Invisible finger-sized hit area around the 6px dot. -->
          <svg:circle cx="0" cy="0" r="16" fill="transparent" />
          <svg:circle cx="0" cy="0" r="6" class="fill-white stroke-zinc-400 stroke-2" />
          @if (port.display !== 'out') {
            <svg:text x="0" y="20" text-anchor="middle" class="fill-zinc-500 text-[10px]">
              {{ port.display }}
            </svg:text>
          }
        </svg:g>
      }
    </svg:g>
  `,
})
export class WorkflowNodeComponent {
  readonly WIDTH = NODE_WIDTH;
  readonly HEIGHT = NODE_HEIGHT;
  readonly HEADER = NODE_HEADER;

  readonly node = input.required<CanvasNode>();
  readonly selected = input<boolean>(false);

  readonly outputPortDown = output<{
    nodeId: string;
    portLabel: string | null;
    event: PointerEvent;
  }>();
  readonly cardPointerDown = output<{ nodeId: string; event: PointerEvent }>();
  readonly selectNode = output<string>();
  readonly nodeContextMenu = output<{ nodeId: string; x: number; y: number }>();

  readonly nodeType = computed<WorkflowNodeType | undefined>(() => getNodeType(this.node().type));

  readonly outputs = computed(() => this.nodeType()?.outputs ?? []);
  readonly hasInputPort = computed(() => (this.nodeType()?.inputPorts ?? 1) > 0);
  readonly icon = computed(() => this.nodeType()?.icon ?? 'Box');
  readonly displayName = computed(() => {
    const cfg = this.node().config as Record<string, unknown> | undefined;
    const label = cfg?.['label'];
    if (typeof label === 'string' && label.trim() !== '') {
      return label;
    }
    return this.nodeType()?.label ?? this.node().type;
  });
  /** Derive a human-readable summary from the node's live config so the
   *  operator can see what each node does without clicking into it. For
   *  the trigger, that's the picked event ("On lead.created"); for send
   *  actions, whether a template is bound; for wait, the duration; else
   *  we fall back to the static registry description. */
  readonly description = computed(() => {
    const type = this.nodeType();
    if (!type) return '';
    const cfg = (this.node().config ?? {}) as Record<string, unknown>;

    if (type.type === 'trigger') {
      const evt = cfg['event_type'];
      if (typeof evt === 'string' && evt.trim()) {
        return `On ${evt}`;
      }
      return 'Pick an event';
    }

    if (type.type.startsWith('send.')) {
      const tpl = cfg['template_id'];
      if (typeof tpl === 'string' && tpl.trim()) {
        return 'Template selected';
      }
      return 'Pick a template';
    }

    if (type.type === 'wait') {
      const dur = cfg['duration'] ?? cfg['delay'];
      if (typeof dur === 'string' && dur.trim()) {
        return `Wait ${dur}`;
      }
      return 'Set a duration';
    }

    return type.description;
  });
  /** Group-derived visual style. Every trigger renders amber, every
   *  send renders sky, etc. — mirrors the palette so the drop reads
   *  as the same node the operator dragged. */
  readonly style = computed<CanvasNodeStyle>(() => {
    const cat = this.nodeType()?.category;
    return cat ? (CANVAS_NODE_STYLE[cat] ?? DEFAULT_NODE_STYLE) : DEFAULT_NODE_STYLE;
  });

  /** SVG path for the header strip — full-width strip with the top
   *  two corners rounded (matching the card's 10px `rx`) and the
   *  bottom edge flat. Kept as a `<path>` because `<rect rx>` rounds
   *  all four corners. */
  readonly headerPath = computed<string>(() => {
    const w = this.WIDTH;
    const h = this.HEADER;
    const r = 10;
    return `M ${r} 0 L ${w - r} 0 A ${r} ${r} 0 0 1 ${w} ${r} L ${w} ${h} L 0 ${h} L 0 ${r} A ${r} ${r} 0 0 1 ${r} 0 Z`;
  });

  /** SVG path for the left accent bar — 4px wide, full height, top-
   *  and bottom-left corners rounded to match the card. */
  readonly accentPath = computed<string>(() => {
    const h = this.HEIGHT;
    const r = 10;
    const w = 4;
    return `M ${r} 0 L ${w} 0 L ${w} ${h} L ${r} ${h} A ${r} ${r} 0 0 1 0 ${h - r} L 0 ${r} A ${r} ${r} 0 0 1 ${r} 0 Z`;
  });

  readonly transform = computed(() => {
    const pos = this.node().position ?? { x: 0, y: 0 };
    return `translate(${pos.x}, ${pos.y})`;
  });
  readonly validationFailed = computed(() => {
    const cfg = this.node().config as Record<string, unknown> | undefined;
    return cfg?.['__valid'] === false;
  });

  outputPortX(index: number, total: number): number {
    if (total <= 1) return this.WIDTH / 2;
    const usable = this.WIDTH - 40;
    const step = usable / (total - 1);
    return 20 + step * index;
  }

  onCardPointerDown(event: PointerEvent): void {
    if (event.button !== 0) return;
    this.cardPointerDown.emit({ nodeId: this.node().id, event });
  }

  onCardClick(event: MouseEvent): void {
    event.stopPropagation();
    this.selectNode.emit(this.node().id);
  }

  onCardContextMenu(event: MouseEvent): void {
    // Right-click anywhere on the card raises the screen-space menu at
    // the cursor. Suppress the native browser menu + canvas pan.
    event.preventDefault();
    event.stopPropagation();
    this.nodeContextMenu.emit({
      nodeId: this.node().id,
      x: event.clientX,
      y: event.clientY,
    });
  }

  onMenuClick(event: MouseEvent): void {
    // The kebab is an explicit affordance for the same menu — anchor it
    // just below the button so it doesn't cover the node header.
    event.preventDefault();
    event.stopPropagation();
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    this.nodeContextMenu.emit({
      nodeId: this.node().id,
      x: rect.right,
      y: rect.bottom + 4,
    });
  }

  onOutputDown(event: PointerEvent, portLabel: string | null): void {
    event.stopPropagation();
    event.preventDefault();
    this.outputPortDown.emit({
      nodeId: this.node().id,
      portLabel,
      event,
    });
  }
}

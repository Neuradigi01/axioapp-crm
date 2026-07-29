import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { CanvasNode } from './canvas-state.service';
import { getNodeType, WorkflowNodeType } from './node-type-registry';

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
 * Edge-creation drag starts from an output port (mousedown on a port
 * circle) — the canvas page listens for `outputPortDown`, tracks the
 * pending edge, and finalises it on `inputPortUp` over another node.
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
      class="select-none"
      (mousedown)="onCardMouseDown($event)"
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

      <svg:rect
        [attr.width]="WIDTH"
        [attr.height]="HEIGHT"
        rx="10"
        ry="10"
        [class]="bodyClass()"
        stroke-width="1.5"
      />

      <svg:rect
        [attr.width]="WIDTH"
        [attr.height]="HEADER"
        rx="10"
        ry="10"
        class="fill-white/60 stroke-transparent"
      />
      <svg:rect [attr.width]="WIDTH" height="1" [attr.y]="HEADER" class="fill-zinc-200" />

      <svg:foreignObject [attr.width]="WIDTH" [attr.height]="HEADER" x="0" y="0">
        <div class="flex items-center gap-2 px-3 h-full text-xs font-semibold text-default">
          <lucide-icon [name]="icon()" class="w-3.5 h-3.5 text-muted"></lucide-icon>
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
        <div class="px-3 text-[11px] leading-snug text-muted">
          {{ description() }}
        </div>
      </svg:foreignObject>

      <svg:foreignObject [attr.x]="WIDTH - 26" y="6" width="20" height="20">
        <button
          type="button"
          class="w-5 h-5 flex items-center justify-center rounded text-faint hover:text-default hover:bg-surface-2"
          (click)="onMenuClick($event)"
          (mousedown)="$event.stopPropagation()"
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
          (mouseup)="onInputUp($event)"
          (mousedown)="$event.stopPropagation()"
        />
      }

      @for (port of outputs(); track port.label || $index; let i = $index) {
        <svg:g
          [attr.transform]="'translate(' + outputPortX(i, outputs().length) + ',' + HEIGHT + ')'"
        >
          <svg:circle
            cx="0"
            cy="0"
            r="6"
            class="fill-white stroke-zinc-400 stroke-2 cursor-crosshair"
            (mousedown)="onOutputDown($event, port.label)"
          />
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
    event: MouseEvent;
  }>();
  readonly inputPortUp = output<{ nodeId: string; event: MouseEvent }>();
  readonly cardMouseDown = output<{ nodeId: string; event: MouseEvent }>();
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
  readonly bodyClass = computed(() => this.nodeType()?.colorClass ?? 'bg-surface-2 border-subtle');
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

  onCardMouseDown(event: MouseEvent): void {
    if (event.button !== 0) return;
    this.cardMouseDown.emit({ nodeId: this.node().id, event });
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

  onOutputDown(event: MouseEvent, portLabel: string | null): void {
    event.stopPropagation();
    event.preventDefault();
    this.outputPortDown.emit({
      nodeId: this.node().id,
      portLabel,
      event,
    });
  }

  onInputUp(event: MouseEvent): void {
    event.stopPropagation();
    this.inputPortUp.emit({ nodeId: this.node().id, event });
  }
}

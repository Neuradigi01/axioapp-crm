import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import {
  CanvasNode,
  CanvasStateService,
} from './canvas-state.service';
import { getNodeType, WorkflowNodeType } from './node-type-registry';


/**
 * Single canvas node — type-agnostic. Renders the rounded card with
 * input port (top edge) and output ports (bottom edge). Click → select;
 * drag → move; "Delete" / "Duplicate" / "Disconnect" exposed via the
 * top-right menu.
 *
 * Pure presentation — every mutation routes through
 * `CanvasStateService` so undo / redo / dirty / auto-save stay in
 * sync.
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
      <svg:rect
        [attr.width]="WIDTH"
        height="1"
        [attr.y]="HEADER"
        class="fill-zinc-200"
      />

      <svg:foreignObject [attr.width]="WIDTH" [attr.height]="HEADER" x="0" y="0">
        <div
          class="flex items-center gap-2 px-3 h-full text-xs font-semibold text-zinc-700"
        >
          <lucide-icon
            [name]="icon()"
            class="w-3.5 h-3.5 text-zinc-600"
          ></lucide-icon>
          <span class="truncate flex-1">{{ displayName() }}</span>
          @if (validationFailed()) {
            <span
              title="Configuration incomplete"
              class="inline-block w-2 h-2 rounded-full bg-rose-500 shrink-0"
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
        <div class="px-3 text-[11px] leading-snug text-zinc-500">
          {{ description() }}
        </div>
      </svg:foreignObject>

      <svg:foreignObject [attr.x]="WIDTH - 26" y="6" width="20" height="20">
        <button
          type="button"
          class="w-5 h-5 flex items-center justify-center rounded text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100"
          (click)="onMenuClick($event)"
          (mousedown)="$event.stopPropagation()"
          aria-label="Node actions"
        >
          <lucide-icon name="MoreVertical" class="w-3.5 h-3.5"></lucide-icon>
        </button>
      </svg:foreignObject>

      @if (menuOpen()) {
        <svg:foreignObject
          [attr.x]="WIDTH - 130"
          [attr.y]="28"
          width="130"
          height="100"
        >
          <div
            class="bg-white border border-zinc-200 rounded-lg shadow-lg overflow-hidden text-xs"
            (mousedown)="$event.stopPropagation()"
          >
            <button
              type="button"
              class="block w-full text-left px-3 py-2 hover:bg-zinc-50"
              (click)="onDuplicate($event)"
            >
              Duplicate
            </button>
            <button
              type="button"
              class="block w-full text-left px-3 py-2 hover:bg-zinc-50"
              (click)="onDisconnect($event)"
            >
              Disconnect
            </button>
            <button
              type="button"
              class="block w-full text-left px-3 py-2 text-rose-600 hover:bg-rose-50"
              (click)="onDelete($event)"
            >
              Delete
            </button>
          </div>
        </svg:foreignObject>
      }

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
          [attr.transform]="
            'translate(' +
            outputPortX(i, outputs().length) +
            ',' +
            HEIGHT +
            ')'
          "
        >
          <svg:circle
            cx="0"
            cy="0"
            r="6"
            class="fill-white stroke-zinc-400 stroke-2 cursor-crosshair"
            (mousedown)="onOutputDown($event, port.label)"
          />
          @if (port.display !== 'out') {
            <svg:text
              x="0"
              y="20"
              text-anchor="middle"
              class="fill-zinc-500 text-[10px]"
            >
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

  private readonly state = inject(CanvasStateService);
  readonly menuOpen = signal(false);

  readonly nodeType = computed<WorkflowNodeType | undefined>(() =>
    getNodeType(this.node().type),
  );

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
  readonly description = computed(() => this.nodeType()?.description ?? '');
  readonly bodyClass = computed(
    () => this.nodeType()?.colorClass ?? 'bg-zinc-50 border-zinc-300',
  );
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
    this.menuOpen.set(false);
    this.cardMouseDown.emit({ nodeId: this.node().id, event });
  }

  onCardClick(event: MouseEvent): void {
    event.stopPropagation();
    this.selectNode.emit(this.node().id);
  }

  onMenuClick(event: MouseEvent): void {
    event.stopPropagation();
    this.menuOpen.update((v) => !v);
  }

  onDuplicate(event: MouseEvent): void {
    event.stopPropagation();
    this.menuOpen.set(false);
    this.state.duplicateNode(this.node().id);
  }

  onDisconnect(event: MouseEvent): void {
    event.stopPropagation();
    this.menuOpen.set(false);
    const id = this.node().id;
    const edges = this.state.edges();
    for (const e of edges) {
      if (e.source === id || e.target === id) {
        this.state.deleteEdge(e.id);
      }
    }
  }

  onDelete(event: MouseEvent): void {
    event.stopPropagation();
    this.menuOpen.set(false);
    if (confirm('Delete this node and its connections?')) {
      this.state.deleteNode(this.node().id);
    }
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

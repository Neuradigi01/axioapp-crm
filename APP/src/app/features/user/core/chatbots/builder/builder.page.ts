import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { ConfirmDialogComponent } from '../../shared/confirm-dialog/confirm-dialog.component';
import { ChatbotsApiService, TriggerConfig } from '../chatbots-api.service';
import { CanvasNode, CanvasStateService } from './canvas-state.service';
import { NodeConfigFormComponent } from './node-config-form/node-config-form.component';
import { NodeTypeMeta, getNodeType } from './node-type-registry';
import { ChatbotPaletteComponent } from './palette/palette.component';
import { TriggerConfigModalComponent } from './trigger-modal/trigger-config.modal';

/**
 * Chatbot builder canvas page (tasks/chatbot-builder Step 13).
 *
 * Route: `/user/chatbots/:id/edit`. Layout mirrors the Pabbly
 * mockup at `tasks/chatbot-builder/mockup.html`: sidebar palette
 * on the left, trigger card at the top of the canvas, absolutely-
 * positioned node cards below.
 *
 * v1 keeps the canvas mechanically simple — nodes are placed by
 * clicking a palette tile (cascade drop), positions stored on the
 * graph. Full drag-and-drop / edge-draw / zoom-pan lands as a
 * Step-14 follow-up alongside the concrete node-component work.
 *
 * Config-on-node (Pabbly signature): clicking a node opens no
 * right drawer — every field lives on the node face. Until the
 * per-node components land in Step 14, config renders as a
 * fallback JSON pre so operators can still save valid graphs.
 */
@Component({
  selector: 'app-chatbot-builder',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    LucideAngularModule,
    ChatbotPaletteComponent,
    TriggerConfigModalComponent,
    ConfirmDialogComponent,
    NodeConfigFormComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './builder.page.html',
})
export class ChatbotBuilderPageComponent {
  private readonly api = inject(ChatbotsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  readonly canvas = inject(CanvasStateService);

  readonly loading = signal<boolean>(true);
  readonly error = signal<string | null>(null);
  readonly triggerModalOpen = signal<boolean>(false);
  readonly deleteNodeId = signal<string | null>(null);

  readonly bot = this.canvas.bot;
  readonly nodes = this.canvas.nodes;
  readonly edges = this.canvas.edges;
  readonly triggerConfig = this.canvas.triggerConfig;
  readonly selectedNodeId = this.canvas.selectedNodeId;
  readonly dirty = this.canvas.dirty;
  readonly saving = this.canvas.saving;
  readonly pendingSourceId = this.canvas.pendingSourceId;

  /** Layout constants matching the template — kept here so the SVG
   *  edge computation and the DOM stay in sync. Node position `x/y`
   *  in the graph is anchored at the top-left of the card AFTER the
   *  trigger-column offset (`TRIGGER_LEFT + TRIGGER_WIDTH + GAP`). */
  private readonly CANVAS_PAD = 24;
  private readonly TRIGGER_LEFT = this.CANVAS_PAD;
  private readonly TRIGGER_TOP = this.CANVAS_PAD;
  private readonly TRIGGER_WIDTH = 320;
  private readonly TRIGGER_HEIGHT = 118;
  private readonly NODE_LEFT_OFFSET = 380;
  private readonly NODE_WIDTH = 320;
  private readonly NODE_HEADER_H = 44;

  /** Where each node's LEFT (input) port lives, absolute canvas
   *  coordinates. */
  inputPortPos(node: CanvasNode): { x: number; y: number } {
    return {
      x: this.NODE_LEFT_OFFSET + node.position.x,
      y: node.position.y + this.NODE_HEADER_H / 2,
    };
  }

  /** Where each node's RIGHT (output) port lives, per label. Labeled
   *  ports are stacked below the header at fixed row heights so a
   *  card of the same width has predictable port coordinates. */
  outputPortPos(node: CanvasNode, labelIndex = 0): { x: number; y: number } {
    return {
      x: this.NODE_LEFT_OFFSET + node.position.x + this.NODE_WIDTH,
      y: node.position.y + this.NODE_HEADER_H / 2 + labelIndex * 22,
    };
  }

  triggerPortPos(): { x: number; y: number } {
    return {
      x: this.TRIGGER_LEFT + this.TRIGGER_WIDTH,
      y: this.TRIGGER_TOP + this.TRIGGER_HEIGHT / 2,
    };
  }

  /** Build the SVG path `d` attribute for a smooth cubic between two
   *  points — control points offset horizontally by half the distance
   *  so edges bend cleanly right-to-left even when nodes overlap
   *  vertically. */
  edgePath(from: { x: number; y: number }, to: { x: number; y: number }): string {
    const dx = Math.max(60, (to.x - from.x) / 2);
    return `M ${from.x} ${from.y} C ${from.x + dx} ${from.y}, ${to.x - dx} ${to.y}, ${to.x} ${to.y}`;
  }

  /** For every persisted edge, resolve its source + target port coords
   *  into a renderable path spec. Returns `null` for orphan edges
   *  (source/target not on the canvas any more). */
  readonly renderedEdges = computed(() => {
    const nodesById = new Map(this.nodes().map((n) => [n.id, n]));
    return this.edges()
      .map((e) => {
        const target = nodesById.get(e.target);
        if (!target) return null;
        const to = this.inputPortPos(target);
        const from =
          e.source === 'trigger'
            ? this.triggerPortPos()
            : (() => {
                const src = nodesById.get(e.source);
                if (!src) return null;
                const meta = getNodeType(src.type);
                const labels = meta?.labels ?? [];
                const idx = e.label && labels.length ? Math.max(0, labels.indexOf(e.label)) : 0;
                return this.outputPortPos(src, idx);
              })();
        if (!from) return null;
        return { id: e.id, label: e.label ?? null, d: this.edgePath(from, to) };
      })
      .filter((x): x is { id: string; label: string | null; d: string } => x !== null);
  });

  /** Show a "click a target to connect" hint while a source port is
   *  active. */
  readonly isConnecting = computed(() => this.pendingSourceId() !== null);

  readonly triggerSummary = computed(() => {
    const cfg = this.triggerConfig();
    if (!cfg) return 'Not configured';
    if (cfg.mode === 'keyword') {
      const n = cfg.keywords?.length ?? 0;
      return n === 0 ? 'Keyword match (no keywords)' : `${n} keyword${n === 1 ? '' : 's'}`;
    }
    if (cfg.mode === 'regex') return 'Regex pattern';
    return 'Any inbound message';
  });

  readonly isLive = computed(() => this.bot()?.status === 'live');

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id');
      if (id) this.loadBot(id);
    });
  }

  private loadBot(id: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .get(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (bot) => {
          this.canvas.loadFrom(bot);
          this.loading.set(false);
        },
        error: (err) => {
          this.error.set(extractApiError(err) ?? 'Failed to load bot.');
          this.loading.set(false);
        },
      });
  }

  save(): void {
    const bot = this.bot();
    if (!bot) return;
    this.canvas.saving.set(true);
    this.error.set(null);
    const graph = this.canvas.serializeGraph();
    const trigger = this.triggerConfig();
    this.api
      .update(bot.id, {
        expected_version: this.canvas.expectedVersion(),
        graph,
        trigger_config: trigger,
        change_note: null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.canvas.bot.set(updated);
          this.canvas.markSaved(updated.version_number);
        },
        error: (err) => {
          this.error.set(extractApiError(err) ?? 'Save failed.');
          this.canvas.saving.set(false);
        },
      });
  }

  toggleLive(): void {
    const bot = this.bot();
    if (!bot) return;
    if (this.dirty()) {
      this.error.set('Save your unsaved changes before toggling Live.');
      return;
    }
    const call = this.isLive() ? this.api.pause(bot.id) : this.api.publish(bot.id);
    call.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (updated) => {
        this.canvas.bot.set(updated);
        this.canvas.markSaved(updated.version_number);
      },
      error: (err) => this.error.set(extractApiError(err) ?? 'Status change failed.'),
    });
  }

  openTriggerModal(): void {
    this.triggerModalOpen.set(true);
  }

  onTriggerSave(cfg: TriggerConfig): void {
    this.canvas.setTriggerConfig(cfg);
    this.triggerModalOpen.set(false);
  }

  onPaletteAdd(_meta: NodeTypeMeta): void {
    // Palette already added the node via canvas service; nothing
    // extra to do here for v1. Hook exists so the builder page can
    // trigger analytics / haptics in future.
  }

  selectNode(nodeId: string): void {
    // If a source port is pending, treat clicks on nodes as connect-
    // completion attempts. Any click on the card itself is treated as
    // "connect to this node's input" for ergonomics.
    if (this.pendingSourceId()) {
      this.canvas.completeConnect(nodeId);
      return;
    }
    this.canvas.selectedNodeId.set(nodeId);
  }

  onOutputPortClick(sourceId: string, label: string | null, evt: MouseEvent): void {
    evt.stopPropagation();
    if (this.pendingSourceId() === sourceId && this.canvas.pendingSourceLabel() === label) {
      this.canvas.cancelConnect();
      return;
    }
    this.canvas.beginConnect(sourceId, label);
  }

  onInputPortClick(targetId: string, evt: MouseEvent): void {
    evt.stopPropagation();
    if (!this.pendingSourceId()) return;
    this.canvas.completeConnect(targetId);
  }

  /** Click on empty canvas — clears any pending connect gesture and
   *  deselects the current node. */
  onCanvasClick(): void {
    if (this.pendingSourceId()) {
      this.canvas.cancelConnect();
      return;
    }
    this.canvas.selectedNodeId.set(null);
  }

  deleteEdge(edgeId: string, evt: MouseEvent): void {
    evt.stopPropagation();
    this.canvas.deleteEdge(edgeId);
  }

  patchNodeConfig(nodeId: string, patch: Record<string, unknown>): void {
    this.canvas.updateNodeConfig(nodeId, patch);
  }

  deleteNode(nodeId: string, evt: MouseEvent): void {
    evt.stopPropagation();
    this.deleteNodeId.set(nodeId);
  }

  cancelDeleteNode(): void {
    this.deleteNodeId.set(null);
  }

  confirmDeleteNode(): void {
    const id = this.deleteNodeId();
    if (!id) return;
    this.canvas.deleteNode(id);
    this.deleteNodeId.set(null);
  }

  nodeMeta(type: string): NodeTypeMeta | undefined {
    return getNodeType(type);
  }

  updateNodeConfigJson(nodeId: string, raw: string): void {
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        this.canvas.updateNodeConfig(nodeId, parsed);
      }
    } catch {
      // Invalid JSON — silently ignore. A future Step 14 per-node
      // form UI replaces this fallback.
    }
  }
}

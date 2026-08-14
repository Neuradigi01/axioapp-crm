import { Injectable, computed, signal } from '@angular/core';

import { ChatbotRead, TriggerConfig } from '../chatbots-api.service';
import { NodeTypeMeta } from './node-type-registry';

/**
 * Canvas state for the chatbot builder (tasks/chatbot-builder Step 13).
 *
 * Signals-first store — the builder page + palette + node
 * components read + patch through this one service. Loading a bot
 * seeds `bot` + serializes its graph into `nodes` + `edges`. Save
 * builds the reverse.
 *
 * `dirty` flips on any mutation; the builder page shows the amber
 * dot in the header + gates the Draft/Live toggle behind a save.
 * `expectedVersion` mirrors `bot.version_number` at load time so
 * the PATCH sends the right optimistic-lock cursor.
 */

export interface CanvasNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  config: Record<string, unknown>;
}

export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  label?: string | null;
}

@Injectable({ providedIn: 'root' })
export class CanvasStateService {
  readonly bot = signal<ChatbotRead | null>(null);
  readonly nodes = signal<CanvasNode[]>([]);
  readonly edges = signal<CanvasEdge[]>([]);
  readonly triggerConfig = signal<TriggerConfig | null>(null);
  readonly selectedNodeId = signal<string | null>(null);
  readonly dirty = signal<boolean>(false);
  readonly saving = signal<boolean>(false);
  readonly expectedVersion = signal<number>(1);

  /** Session-only position of the trigger card on the canvas. The
   *  trigger isn't a node in the backend graph (see
   *  `serializeGraph` — trigger-sourced edges are UI-only), so its
   *  position isn't persisted. Resets to `(0, 0)` on every load. */
  readonly triggerPosition = signal<{ x: number; y: number }>({ x: 0, y: 0 });

  /** Canvas zoom (session-only). `1` = 100 %. Bounded to [0.25, 2]
   *  by `setZoom` / `zoomIn` / `zoomOut`. Applied via CSS transform
   *  on the canvas content wrapper. */
  readonly zoom = signal<number>(1);
  /** Palette open / collapsed (session-only). Collapsed shrinks the
   *  left rail to a narrow strip so the operator sees more canvas
   *  while designing. */
  readonly paletteCollapsed = signal<boolean>(false);

  private readonly ZOOM_MIN = 0.25;
  private readonly ZOOM_MAX = 2;
  private readonly ZOOM_STEPS: readonly number[] = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];

  setZoom(next: number): void {
    const clamped = Math.min(this.ZOOM_MAX, Math.max(this.ZOOM_MIN, next));
    this.zoom.set(Math.round(clamped * 100) / 100);
  }

  zoomIn(): void {
    const cur = this.zoom();
    const next = this.ZOOM_STEPS.find((z) => z > cur) ?? this.ZOOM_MAX;
    this.setZoom(next);
  }

  zoomOut(): void {
    const cur = this.zoom();
    const next = [...this.ZOOM_STEPS].reverse().find((z) => z < cur) ?? this.ZOOM_MIN;
    this.setZoom(next);
  }

  zoomReset(): void {
    this.setZoom(1);
  }

  togglePalette(): void {
    this.paletteCollapsed.update((v) => !v);
  }

  /** Click-to-connect state — set to the source node id (or literal
   *  `'trigger'`) when the user clicks an output port. The next
   *  input-port click on a different node closes the pair into an
   *  edge. Clicking empty canvas / Escape clears it. */
  readonly pendingSourceId = signal<string | null>(null);
  /** Optional label for the pending edge (labeled ports carry
   *  `answered / invalid / timeout / …`). */
  readonly pendingSourceLabel = signal<string | null>(null);

  readonly selectedNode = computed(() => {
    const id = this.selectedNodeId();
    if (!id) return null;
    return this.nodes().find((n) => n.id === id) ?? null;
  });

  loadFrom(bot: ChatbotRead): void {
    this.bot.set(bot);
    this.triggerConfig.set({ ...bot.trigger_config });
    const graph = bot.graph ?? { nodes: [], edges: [] };
    const loadedNodes = (graph.nodes ?? []).map((n) => ({
      id: n.id,
      type: n.type,
      position: n.position ?? { x: 40, y: 40 },
      config: this.clone(n.config ?? {}),
    }));
    const loadedEdges: CanvasEdge[] = (graph.edges ?? []).map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label ?? null,
    }));

    // Re-derive the UI-only trigger→entry edge on load. The entry
    // point is the first node that has no incoming edge; `addNode`
    // wired one in for empty graphs, but stored bots may have been
    // built via API or older UI so we walk the topology here.
    const incomingIds = new Set(loadedEdges.map((e) => e.target));
    const entry = loadedNodes.find((n) => !incomingIds.has(n.id));
    if (entry) {
      loadedEdges.push({
        id: `e_trigger_${entry.id}`,
        source: 'trigger',
        target: entry.id,
        label: null,
      });
    }

    this.nodes.set(loadedNodes);
    this.edges.set(loadedEdges);
    this.selectedNodeId.set(null);
    this.dirty.set(false);
    this.expectedVersion.set(bot.version_number);
    this.triggerPosition.set({ x: 0, y: 0 });
  }

  reset(): void {
    this.bot.set(null);
    this.nodes.set([]);
    this.edges.set([]);
    this.triggerConfig.set(null);
    this.selectedNodeId.set(null);
    this.dirty.set(false);
    this.saving.set(false);
    this.expectedVersion.set(1);
    this.pendingSourceId.set(null);
    this.pendingSourceLabel.set(null);
    this.triggerPosition.set({ x: 0, y: 0 });
    this.zoom.set(1);
    this.paletteCollapsed.set(false);
  }

  addNode(meta: NodeTypeMeta, position: { x: number; y: number }): CanvasNode {
    const id = this.generateNodeId(meta.type);
    const node: CanvasNode = {
      id,
      type: meta.type,
      position,
      config: this.clone(meta.defaultConfig),
    };
    const wasEmpty = this.nodes().length === 0;
    const triggerAlreadyWired = this.edges().some((e) => e.source === 'trigger');
    this.nodes.update((rows) => [...rows, node]);
    this.selectedNodeId.set(id);
    this.dirty.set(true);
    // First node on a fresh canvas auto-wires from the trigger so the
    // flow visually reads "Trigger → this node" without a manual
    // click-to-connect gesture. Skipped if the operator already
    // pointed the trigger somewhere else.
    if (wasEmpty && !triggerAlreadyWired) {
      this.addEdge('trigger', id, null);
    }
    return node;
  }

  /** Start / cancel / complete a click-to-connect gesture. */
  beginConnect(sourceId: string, label: string | null = null): void {
    this.pendingSourceId.set(sourceId);
    this.pendingSourceLabel.set(label);
  }

  cancelConnect(): void {
    this.pendingSourceId.set(null);
    this.pendingSourceLabel.set(null);
  }

  completeConnect(targetId: string): boolean {
    const src = this.pendingSourceId();
    if (!src) return false;
    if (src === targetId) {
      this.cancelConnect();
      return false;
    }
    const label = this.pendingSourceLabel();
    // Drop any existing edge on the same source+label so a port can only
    // point to one target at a time (Pabbly convention). Trigger edges
    // are virtual (source = 'trigger') and stored in the same list.
    this.edges.update((rows) =>
      rows.filter((e) => !(e.source === src && (e.label ?? null) === label)),
    );
    this.addEdge(src, targetId, label);
    this.cancelConnect();
    return true;
  }

  updateNodeConfig(nodeId: string, patch: Record<string, unknown>): void {
    this.nodes.update((rows) =>
      rows.map((n) =>
        n.id === nodeId ? { ...n, config: { ...this.clone(n.config), ...patch } } : n,
      ),
    );
    this.dirty.set(true);
  }

  updateNodePosition(nodeId: string, position: { x: number; y: number }): void {
    this.nodes.update((rows) => rows.map((n) => (n.id === nodeId ? { ...n, position } : n)));
    this.dirty.set(true);
  }

  deleteNode(nodeId: string): void {
    this.nodes.update((rows) => rows.filter((n) => n.id !== nodeId));
    this.edges.update((rows) => rows.filter((e) => e.source !== nodeId && e.target !== nodeId));
    if (this.selectedNodeId() === nodeId) this.selectedNodeId.set(null);
    this.dirty.set(true);
  }

  addEdge(source: string, target: string, label: string | null = null): CanvasEdge {
    const id = this.generateEdgeId();
    const edge: CanvasEdge = { id, source, target, label };
    this.edges.update((rows) => [...rows, edge]);
    this.dirty.set(true);
    return edge;
  }

  deleteEdge(edgeId: string): void {
    this.edges.update((rows) => rows.filter((e) => e.id !== edgeId));
    this.dirty.set(true);
  }

  setTriggerConfig(cfg: TriggerConfig): void {
    this.triggerConfig.set(cfg);
    this.dirty.set(true);
  }

  serializeGraph(): { nodes: CanvasNode[]; edges: CanvasEdge[] } {
    // `source: 'trigger'` is a UI-only virtual edge that lets the
    // canvas draw "Trigger → first node" cleanly. The backend graph
    // schema is a DAG of real nodes only (`core/chatbots/graph.py`
    // Kahn's-algorithm cycle check would treat a `trigger` source as
    // an unresolved reference and reject the save). Strip them.
    return {
      nodes: this.nodes().map((n) => this.clone(n)),
      edges: this.edges()
        .filter((e) => e.source !== 'trigger')
        .map((e) => this.clone(e)),
    };
  }

  markSaved(newVersion: number): void {
    this.dirty.set(false);
    this.saving.set(false);
    this.expectedVersion.set(newVersion);
  }

  private generateNodeId(type: string): string {
    return `${type}_${Math.random().toString(36).slice(2, 8)}`;
  }

  private generateEdgeId(): string {
    return `e_${Math.random().toString(36).slice(2, 10)}`;
  }

  private clone<T>(value: T): T {
    return JSON.parse(JSON.stringify(value)) as T;
  }
}

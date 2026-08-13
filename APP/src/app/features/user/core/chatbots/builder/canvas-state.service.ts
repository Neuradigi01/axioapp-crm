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

  readonly selectedNode = computed(() => {
    const id = this.selectedNodeId();
    if (!id) return null;
    return this.nodes().find((n) => n.id === id) ?? null;
  });

  loadFrom(bot: ChatbotRead): void {
    this.bot.set(bot);
    this.triggerConfig.set({ ...bot.trigger_config });
    const graph = bot.graph ?? { nodes: [], edges: [] };
    this.nodes.set(
      (graph.nodes ?? []).map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position ?? { x: 40, y: 40 },
        config: this.clone(n.config ?? {}),
      })),
    );
    this.edges.set(
      (graph.edges ?? []).map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label ?? null,
      })),
    );
    this.selectedNodeId.set(null);
    this.dirty.set(false);
    this.expectedVersion.set(bot.version_number);
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
  }

  addNode(meta: NodeTypeMeta, position: { x: number; y: number }): CanvasNode {
    const id = this.generateNodeId(meta.type);
    const node: CanvasNode = {
      id,
      type: meta.type,
      position,
      config: this.clone(meta.defaultConfig),
    };
    this.nodes.update((rows) => [...rows, node]);
    this.selectedNodeId.set(id);
    this.dirty.set(true);
    return node;
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
    return {
      nodes: this.nodes().map((n) => this.clone(n)),
      edges: this.edges().map((e) => this.clone(e)),
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

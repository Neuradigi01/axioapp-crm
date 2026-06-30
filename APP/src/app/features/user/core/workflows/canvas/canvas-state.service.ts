import { Injectable, computed, signal } from '@angular/core';

import {
  WorkflowGraph,
  WorkflowRead,
} from '../workflows-api.service';
import { getNodeType } from './node-type-registry';


/**
 * Per-tab canvas state for the workflow editor.
 *
 * Signal-based store, fed by `load(workflow)` on enter and flushed by
 * `serializeGraph()` on save. Undo/redo runs off a bounded snapshot
 * stack (max 50 entries) — every mutation method `push`es the current
 * graph onto the stack BEFORE applying the change, then sets dirty.
 *
 * Coordinate system: SVG units (1px = 1 unit). `pan` is the canvas
 * translation; `zoom` is a multiplier in [0.25, 4.0]. The canvas page
 * applies them via a single SVG `<g transform="translate(...) scale(...)">`.
 *
 * Auto-save: the page schedules a 30-second timer that calls
 * `flush()` when dirty AND the workflow is in draft. The spec mirrors
 * the templates editor pattern.
 *
 * State is NOT shared across browser tabs; future polish step could add
 * a BroadcastChannel notice so a stale tab gets the "another tab edited
 * this workflow" banner.
 */


export type CanvasNode = NonNullable<WorkflowGraph['nodes']>[number];
export type CanvasEdge = NonNullable<WorkflowGraph['edges']>[number];


const MAX_UNDO = 50;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 4.0;
const DEFAULT_NODE_WIDTH = 220;
const DEFAULT_NODE_HEIGHT = 110;


function cloneGraph(graph: WorkflowGraph): WorkflowGraph {
  return {
    nodes: graph.nodes.map((n) => ({
      ...n,
      position: n.position ? { ...n.position } : undefined,
      config: n.config ? { ...n.config } : undefined,
    })),
    edges: graph.edges.map((e) => ({ ...e })),
  };
}


function emptyGraph(): WorkflowGraph {
  return { nodes: [], edges: [] };
}


function newNodeId(): string {
  // Sufficient uniqueness within a single workflow; the engine treats
  // node ids as opaque strings.
  return `n_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`;
}


function newEdgeId(): string {
  return `e_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`;
}


@Injectable()
export class CanvasStateService {
  // --- live state -----------------------------------------------------

  private readonly nodesSig = signal<CanvasNode[]>([]);
  private readonly edgesSig = signal<CanvasEdge[]>([]);
  private readonly selectedNodeIdSig = signal<string | null>(null);
  private readonly zoomSig = signal<number>(1);
  private readonly panSig = signal<{ x: number; y: number }>({ x: 0, y: 0 });
  private readonly dirtySig = signal<boolean>(false);
  private readonly nameSig = signal<string>('');
  private readonly statusSig = signal<WorkflowRead['status']>('draft');
  private readonly workflowIdSig = signal<string | null>(null);

  // --- undo / redo ----------------------------------------------------

  private readonly undoStack: WorkflowGraph[] = [];
  private readonly redoStack: WorkflowGraph[] = [];
  readonly canUndo = signal<boolean>(false);
  readonly canRedo = signal<boolean>(false);

  // --- public read-only signals ---------------------------------------

  readonly nodes = this.nodesSig.asReadonly();
  readonly edges = this.edgesSig.asReadonly();
  readonly selectedNodeId = this.selectedNodeIdSig.asReadonly();
  readonly zoom = this.zoomSig.asReadonly();
  readonly pan = this.panSig.asReadonly();
  readonly dirty = this.dirtySig.asReadonly();
  readonly name = this.nameSig.asReadonly();
  readonly status = this.statusSig.asReadonly();
  readonly workflowId = this.workflowIdSig.asReadonly();

  readonly selectedNode = computed<CanvasNode | null>(() => {
    const id = this.selectedNodeIdSig();
    if (id === null) return null;
    return this.nodesSig().find((n) => n.id === id) ?? null;
  });


  // --- load + serialize -----------------------------------------------

  load(workflow: WorkflowRead): void {
    const graph = cloneGraph(workflow.graph ?? emptyGraph());
    this.workflowIdSig.set(workflow.id);
    this.nameSig.set(workflow.name);
    this.statusSig.set(workflow.status);
    this.nodesSig.set(graph.nodes);
    this.edgesSig.set(graph.edges);
    this.selectedNodeIdSig.set(null);
    this.dirtySig.set(false);
    this.zoomSig.set(1);
    this.panSig.set({ x: 0, y: 0 });
    this.undoStack.length = 0;
    this.redoStack.length = 0;
    this.canUndo.set(false);
    this.canRedo.set(false);
  }

  loadBlank(name: string): void {
    this.workflowIdSig.set(null);
    this.nameSig.set(name);
    this.statusSig.set('draft');
    this.nodesSig.set([]);
    this.edgesSig.set([]);
    this.selectedNodeIdSig.set(null);
    this.dirtySig.set(true);
    this.zoomSig.set(1);
    this.panSig.set({ x: 0, y: 0 });
    this.undoStack.length = 0;
    this.redoStack.length = 0;
    this.canUndo.set(false);
    this.canRedo.set(false);
  }

  serializeGraph(): WorkflowGraph {
    return cloneGraph({
      nodes: this.nodesSig(),
      edges: this.edgesSig(),
    });
  }

  /** Swap in a graph for preview-only — used by the version-history
   *  drawer's "View" action to render a historical version on the
   *  canvas without touching dirty/undo/redo state. The caller is
   *  responsible for snapshotting the current graph and calling
   *  `loadPreview(backup)` again when the user clicks "Back to
   *  current". */
  loadPreview(graph: WorkflowGraph): void {
    const cloned = cloneGraph(graph);
    this.nodesSig.set(cloned.nodes);
    this.edgesSig.set(cloned.edges);
    this.selectedNodeIdSig.set(null);
  }

  clearDirty(): void {
    this.dirtySig.set(false);
  }

  setName(value: string): void {
    if (value === this.nameSig()) return;
    this.nameSig.set(value);
    this.dirtySig.set(true);
  }

  setStatus(value: WorkflowRead['status']): void {
    this.statusSig.set(value);
  }

  setWorkflowId(value: string): void {
    this.workflowIdSig.set(value);
  }


  // --- undo / redo plumbing -------------------------------------------

  private pushUndo(): void {
    const snapshot = cloneGraph({
      nodes: this.nodesSig(),
      edges: this.edgesSig(),
    });
    this.undoStack.push(snapshot);
    if (this.undoStack.length > MAX_UNDO) {
      this.undoStack.shift();
    }
    // A new mutation invalidates the redo stack.
    this.redoStack.length = 0;
    this.canUndo.set(true);
    this.canRedo.set(false);
  }

  undo(): void {
    const snapshot = this.undoStack.pop();
    if (!snapshot) return;
    const current = cloneGraph({
      nodes: this.nodesSig(),
      edges: this.edgesSig(),
    });
    this.redoStack.push(current);
    this.nodesSig.set(snapshot.nodes);
    this.edgesSig.set(snapshot.edges);
    this.dirtySig.set(true);
    this.canUndo.set(this.undoStack.length > 0);
    this.canRedo.set(true);
  }

  redo(): void {
    const snapshot = this.redoStack.pop();
    if (!snapshot) return;
    const current = cloneGraph({
      nodes: this.nodesSig(),
      edges: this.edgesSig(),
    });
    this.undoStack.push(current);
    this.nodesSig.set(snapshot.nodes);
    this.edgesSig.set(snapshot.edges);
    this.dirtySig.set(true);
    this.canUndo.set(true);
    this.canRedo.set(this.redoStack.length > 0);
  }


  // --- node mutations -------------------------------------------------

  addNode(
    type: string,
    position: { x: number; y: number },
    extras: { label?: string; config?: Record<string, unknown> } = {},
  ): CanvasNode {
    this.pushUndo();
    const nodeType = getNodeType(type);
    const node: CanvasNode = {
      id: newNodeId(),
      type,
      position: { x: Math.round(position.x), y: Math.round(position.y) },
      config: {
        label: extras.label ?? nodeType?.label ?? type,
        ...(extras.config ?? {}),
      },
    };
    this.nodesSig.update((arr) => [...arr, node]);
    this.dirtySig.set(true);
    return node;
  }

  deleteNode(nodeId: string): void {
    if (!this.nodesSig().some((n) => n.id === nodeId)) return;
    this.pushUndo();
    this.nodesSig.update((arr) => arr.filter((n) => n.id !== nodeId));
    this.edgesSig.update((arr) =>
      arr.filter((e) => e.source !== nodeId && e.target !== nodeId),
    );
    if (this.selectedNodeIdSig() === nodeId) {
      this.selectedNodeIdSig.set(null);
    }
    this.dirtySig.set(true);
  }

  duplicateNode(nodeId: string): CanvasNode | null {
    const src = this.nodesSig().find((n) => n.id === nodeId);
    if (!src) return null;
    this.pushUndo();
    const dup: CanvasNode = {
      id: newNodeId(),
      type: src.type,
      position: {
        x: (src.position?.x ?? 0) + 60,
        y: (src.position?.y ?? 0) + 60,
      },
      config: src.config ? { ...src.config } : {},
    };
    this.nodesSig.update((arr) => [...arr, dup]);
    this.dirtySig.set(true);
    return dup;
  }

  moveNode(nodeId: string, position: { x: number; y: number }): void {
    // Drag-end commits an undo entry; intermediate drag moves should
    // use `moveNodeLive` which mutates without pushing undo.
    if (!this.nodesSig().some((n) => n.id === nodeId)) return;
    this.pushUndo();
    this.nodesSig.update((arr) =>
      arr.map((n) =>
        n.id === nodeId
          ? {
              ...n,
              position: {
                x: Math.round(position.x),
                y: Math.round(position.y),
              },
            }
          : n,
      ),
    );
    this.dirtySig.set(true);
  }

  moveNodeLive(nodeId: string, position: { x: number; y: number }): void {
    // Drag-time live updates without undo bloat; the final drag-end
    // call uses `moveNode` to record the snapshot.
    this.nodesSig.update((arr) =>
      arr.map((n) =>
        n.id === nodeId
          ? {
              ...n,
              position: {
                x: Math.round(position.x),
                y: Math.round(position.y),
              },
            }
          : n,
      ),
    );
  }

  updateNodeConfig(nodeId: string, patch: Record<string, unknown>): void {
    if (!this.nodesSig().some((n) => n.id === nodeId)) return;
    this.pushUndo();
    this.nodesSig.update((arr) =>
      arr.map((n) =>
        n.id === nodeId
          ? { ...n, config: { ...(n.config ?? {}), ...patch } }
          : n,
      ),
    );
    this.dirtySig.set(true);
  }

  selectNode(nodeId: string | null): void {
    this.selectedNodeIdSig.set(nodeId);
  }


  // --- edge mutations -------------------------------------------------

  addEdge(
    source: string,
    target: string,
    label: string | null = null,
  ): CanvasEdge | null {
    // Reject self-loops + cycles to the same target.
    if (source === target) return null;
    // Reject duplicate edges (same source/target/label).
    if (
      this.edgesSig().some(
        (e) =>
          e.source === source && e.target === target && (e.label ?? null) === label,
      )
    ) {
      return null;
    }
    // Target must have an input port (anything but trigger nodes).
    const targetNode = this.nodesSig().find((n) => n.id === target);
    if (!targetNode) return null;
    const targetType = getNodeType(targetNode.type);
    if (targetType?.inputPorts === 0) return null;

    this.pushUndo();
    const edge: CanvasEdge = {
      id: newEdgeId(),
      source,
      target,
      label,
    };
    this.edgesSig.update((arr) => [...arr, edge]);
    this.dirtySig.set(true);
    return edge;
  }

  deleteEdge(edgeId: string): void {
    if (!this.edgesSig().some((e) => e.id === edgeId)) return;
    this.pushUndo();
    this.edgesSig.update((arr) => arr.filter((e) => e.id !== edgeId));
    this.dirtySig.set(true);
  }


  // --- camera ---------------------------------------------------------

  setZoom(zoom: number): void {
    const clamped = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
    this.zoomSig.set(clamped);
  }

  setPan(pan: { x: number; y: number }): void {
    this.panSig.set(pan);
  }

  fitToView(viewport: { width: number; height: number }): void {
    const nodes = this.nodesSig();
    if (nodes.length === 0) {
      this.zoomSig.set(1);
      this.panSig.set({ x: 0, y: 0 });
      return;
    }
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const n of nodes) {
      const x = n.position?.x ?? 0;
      const y = n.position?.y ?? 0;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x + DEFAULT_NODE_WIDTH);
      maxY = Math.max(maxY, y + DEFAULT_NODE_HEIGHT);
    }
    const PAD = 80;
    const contentW = maxX - minX + PAD * 2;
    const contentH = maxY - minY + PAD * 2;
    const zx = viewport.width / contentW;
    const zy = viewport.height / contentH;
    const z = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.min(zx, zy, 1)));
    const px = (viewport.width - contentW * z) / 2 - (minX - PAD) * z;
    const py = (viewport.height - contentH * z) / 2 - (minY - PAD) * z;
    this.zoomSig.set(z);
    this.panSig.set({ x: px, y: py });
  }
}

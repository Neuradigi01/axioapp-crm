import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  ViewChild,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  CanvasNode,
  CanvasStateService,
} from './canvas-state.service';
import { WorkflowEdgeComponent } from './edge.component';
import { ImportModalComponent } from './import-modal.component';
import { NodeEditorComponent } from './node-editor.component';
import { NodePaletteComponent } from './node-palette.component';
import {
  NODE_HEIGHT,
  NODE_WIDTH,
  WorkflowNodeComponent,
} from './node.component';
import { getNodeType } from './node-type-registry';
import { SaveChangeNoteModalComponent } from './save-change-note.modal.component';
import { VersionHistoryDrawerComponent } from './version-history-drawer.component';
import {
  WorkflowExportBody,
  WorkflowGraph,
  WorkflowRead,
  WorkflowStatus,
  WorkflowTestFireResponse,
  WorkflowVersionDetail,
  WorkflowsApiService,
} from '../workflows-api.service';
import { WorkflowStatusBadgeComponent } from '../workflow-status-badge.component';


/**
 * The marquee surface — Angular canvas at `/user/workflows/:id` where
 * operators drag nodes from the palette, drop on the SVG canvas,
 * connect edges, and save.
 *
 * Layout: left palette (300px) · main canvas (flex-fill) · right
 * drawer (440px, opens on node click — Step 15 fills the body).
 *
 * Camera: pan = drag empty space; zoom = Ctrl+wheel; both bound to a
 * single SVG `<g>` transform.
 *
 * Edge creation: mousedown on an output port → start tracking → drag
 * to draw a "rubber-band" path → mouseup on a target input port =
 * commit the edge; mouseup elsewhere = cancel.
 *
 * Auto-save: 30-second timer flushes `dirty + status='draft'` to the
 * backend.
 *
 * Status transitions / cloning / activate / pause / discard / run
 * history all use the existing `workflows-api.service` surfaces.
 */


type CursorPoint = { x: number; y: number };
type PendingEdge = {
  sourceNodeId: string;
  sourcePortLabel: string | null;
  start: CursorPoint;
  cursor: CursorPoint;
};


const AUTOSAVE_INTERVAL_MS = 30_000;


@Component({
  selector: 'app-workflow-canvas',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [CanvasStateService],
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    LucideAngularModule,
    ImportModalComponent,
    NodeEditorComponent,
    NodePaletteComponent,
    SaveChangeNoteModalComponent,
    VersionHistoryDrawerComponent,
    WorkflowNodeComponent,
    WorkflowEdgeComponent,
    WorkflowStatusBadgeComponent,
  ],
  templateUrl: './workflow-canvas.page.html',
})
export class WorkflowCanvasPageComponent {
  readonly state = inject(CanvasStateService);
  private readonly api = inject(WorkflowsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  @ViewChild('canvasRoot', { static: false })
  canvasRoot!: ElementRef<SVGSVGElement>;

  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);
  readonly testFireBusy = signal(false);
  readonly testFireTrace = signal<WorkflowTestFireResponse | null>(null);

  // Step 17 — version history + import/export.
  readonly showVersionDrawer = signal(false);
  readonly viewingVersion = signal<number | null>(null);
  private previewBackup: WorkflowGraph | null = null;
  readonly showImportModal = signal(false);
  readonly importBusy = signal(false);
  readonly showChangeNoteModal = signal(false);

  // Camera + edge-drag local state.
  readonly pendingEdge = signal<PendingEdge | null>(null);
  private panDrag: { start: CursorPoint; pan0: CursorPoint } | null = null;
  private nodeDrag:
    | {
        nodeId: string;
        start: CursorPoint;
        initialPos: CursorPoint;
        moved: boolean;
      }
    | null = null;

  readonly transform = computed(() => {
    const z = this.state.zoom();
    const p = this.state.pan();
    return `translate(${p.x}, ${p.y}) scale(${z})`;
  });

  readonly zoomPercent = computed(() => Math.round(this.state.zoom() * 100));

  readonly nodeById = computed(() => {
    const m = new Map<string, CanvasNode>();
    for (const n of this.state.nodes()) {
      m.set(n.id, n);
    }
    return m;
  });

  readonly pendingEdgePath = computed(() => {
    const p = this.pendingEdge();
    if (!p) return '';
    const dy = Math.max(60, Math.abs(p.cursor.y - p.start.y) * 0.5);
    return `M ${p.start.x} ${p.start.y} C ${p.start.x} ${p.start.y + dy}, ${
      p.cursor.x
    } ${p.cursor.y - dy}, ${p.cursor.x} ${p.cursor.y}`;
  });


  constructor() {
    // Boot — load existing workflow OR initialise a blank one.
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      const id = params.get('id');
      if (id && id !== 'new') {
        this.loadExisting(id);
      } else {
        this.state.loadBlank('Untitled workflow');
        this.loading.set(false);
      }
    });

    // Auto-save loop — fires every AUTOSAVE_INTERVAL_MS. Only flushes
    // when the workflow is dirty AND in draft status.
    const tick = window.setInterval(() => {
      if (
        this.state.dirty() &&
        this.state.status() === 'draft' &&
        this.state.workflowId()
      ) {
        this.save({ silent: true });
      }
    }, AUTOSAVE_INTERVAL_MS);
    this.destroyRef.onDestroy(() => clearInterval(tick));

    // Warn before navigation when dirty.
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (this.state.dirty()) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', beforeUnload);
    this.destroyRef.onDestroy(() =>
      window.removeEventListener('beforeunload', beforeUnload),
    );
  }


  // --- Load / Save / lifecycle ----------------------------------------

  private loadExisting(id: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .get(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (workflow) => {
          this.state.load(workflow);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Could not load workflow.');
          this.loading.set(false);
        },
      });
  }

  save(opts: { silent?: boolean; changeNote?: string } = {}): void {
    // Step 17 — explicit Save Draft on an existing workflow pops the
    // change-note modal so the version row gets a meaningful label.
    // Auto-save (`silent: true`) and brand-new workflows skip it.
    const id = this.state.workflowId();
    if (
      id &&
      !opts.silent &&
      opts.changeNote === undefined &&
      this.state.dirty()
    ) {
      this.showChangeNoteModal.set(true);
      return;
    }
    this.flushSave(opts);
  }

  private flushSave(
    opts: { silent?: boolean; changeNote?: string } = {},
  ): void {
    const id = this.state.workflowId();
    const graph = this.state.serializeGraph();
    const name = this.state.name().trim() || 'Untitled workflow';
    this.saving.set(true);
    this.error.set(null);

    const patchBody: {
      name: string;
      graph: typeof graph;
      change_note?: string;
    } = { name, graph };
    if (opts.changeNote) patchBody.change_note = opts.changeNote;

    const obs = id
      ? this.api.patch(id, patchBody)
      : this.api.create({ name, graph });

    obs.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (workflow) => {
        this.state.setWorkflowId(workflow.id);
        this.state.setStatus(workflow.status);
        this.state.clearDirty();
        this.saving.set(false);
        if (!id && !opts.silent) {
          // Created — swap the URL so subsequent refreshes load the
          // workflow rather than re-creating blanks.
          this.router.navigate(
            ['/user/workflows', workflow.id],
            { replaceUrl: true },
          );
        }
      },
      error: (err: HttpErrorResponse) => {
        this.error.set(extractApiError(err) ?? 'Save failed.');
        this.saving.set(false);
      },
    });
  }

  // --- Step 17 — change-note + version + import/export -------------

  confirmChangeNote(payload: { note: string }): void {
    this.showChangeNoteModal.set(false);
    this.flushSave({ changeNote: payload.note });
  }

  cancelChangeNote(): void {
    if (this.saving()) return;
    this.showChangeNoteModal.set(false);
  }

  toggleVersionDrawer(): void {
    this.showVersionDrawer.update((open) => !open);
  }

  closeVersionDrawer(): void {
    if (this.viewingVersion() !== null) {
      this.backToCurrentFromVersion();
    }
    this.showVersionDrawer.set(false);
  }

  viewHistoricalVersion(detail: WorkflowVersionDetail): void {
    // Snapshot the current live graph so we can put it back.
    if (this.viewingVersion() === null) {
      this.previewBackup = this.state.serializeGraph();
    }
    this.state.loadPreview(detail.graph);
    this.viewingVersion.set(detail.version);
  }

  backToCurrentFromVersion(): void {
    if (this.previewBackup) {
      this.state.loadPreview(this.previewBackup);
    }
    this.previewBackup = null;
    this.viewingVersion.set(null);
  }

  rollbackToVersion(payload: { version: number; changeNote: string }): void {
    const id = this.state.workflowId();
    if (!id) return;
    this.saving.set(true);
    this.api
      .rollback(id, {
        target_version: payload.version,
        change_note: payload.changeNote,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (workflow) => {
          // Drop the preview overlay (rollback already replaced the
          // live graph), reload state from the fresh row, and refresh
          // the drawer so the new version row appears.
          this.previewBackup = null;
          this.viewingVersion.set(null);
          this.state.load(workflow);
          this.saving.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Rollback failed.');
          this.saving.set(false);
        },
      });
  }

  exportWorkflow(): void {
    const id = this.state.workflowId();
    if (!id) return;
    this.api
      .exportWorkflow(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (body) => this.downloadJson(body),
        error: (err: HttpErrorResponse) =>
          this.error.set(extractApiError(err) ?? 'Export failed.'),
      });
  }

  private downloadJson(body: WorkflowExportBody): void {
    const filename =
      (body.name || 'workflow')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '') + '.workflow.json';
    const blob = new Blob([JSON.stringify(body, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  openImportModal(): void {
    this.showImportModal.set(true);
  }

  cancelImport(): void {
    if (this.importBusy()) return;
    this.showImportModal.set(false);
  }

  confirmImport(payload: {
    body: WorkflowExportBody;
    name: string | null;
  }): void {
    this.importBusy.set(true);
    this.api
      .importWorkflow({ json: payload.body, name: payload.name })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (workflow) => {
          this.importBusy.set(false);
          this.showImportModal.set(false);
          this.router.navigate(['/user/workflows', workflow.id]);
        },
        error: (err: HttpErrorResponse) => {
          this.importBusy.set(false);
          this.error.set(extractApiError(err) ?? 'Import failed.');
        },
      });
  }

  activate(): void {
    const id = this.state.workflowId();
    if (!id) return;
    if (this.state.dirty()) {
      if (!confirm('You have unsaved changes — save first?')) return;
      this.save();
    }
    this.api
      .activate(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (workflow) => this.state.setStatus(workflow.status),
        error: (err) =>
          this.error.set(extractApiError(err) ?? 'Activate failed.'),
      });
  }

  pause(): void {
    const id = this.state.workflowId();
    if (!id) return;
    this.api
      .pause(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (workflow) => this.state.setStatus(workflow.status),
        error: (err) =>
          this.error.set(extractApiError(err) ?? 'Pause failed.'),
      });
  }

  discard(): void {
    if (!this.state.dirty()) return;
    if (
      !confirm(
        'Discard unsaved changes? The canvas will revert to the last saved state.',
      )
    ) {
      return;
    }
    const id = this.state.workflowId();
    if (id) {
      this.loadExisting(id);
    } else {
      this.state.loadBlank(this.state.name() || 'Untitled workflow');
    }
  }

  testFire(): void {
    const id = this.state.workflowId();
    if (!id) return;
    if (this.state.dirty()) {
      if (
        !confirm(
          'Save before test-firing? The dry-run uses the persisted graph.',
        )
      ) {
        return;
      }
      this.save();
    }
    this.testFireBusy.set(true);
    this.testFireTrace.set(null);
    this.api
      .testFire(id, {})
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (trace) => {
          this.testFireTrace.set(trace);
          this.testFireBusy.set(false);
        },
        error: (err) => {
          this.error.set(extractApiError(err) ?? 'Test fire failed.');
          this.testFireBusy.set(false);
        },
      });
  }


  // --- Camera (pan + zoom) --------------------------------------------

  onCanvasMouseDown(event: MouseEvent): void {
    // Empty-space drag → pan. Node drag is handled by the node's own
    // mousedown which calls `onNodeMouseDown`.
    if (event.button !== 0) return;
    if (event.target !== event.currentTarget) {
      // Click inside an SVG group → don't pan.
      const tag = (event.target as Element).tagName;
      if (tag !== 'rect' || (event.target as Element).id !== 'workflow-bg') {
        return;
      }
    }
    this.panDrag = {
      start: { x: event.clientX, y: event.clientY },
      pan0: { ...this.state.pan() },
    };
    this.state.selectNode(null);
  }

  @HostListener('window:mousemove', ['$event'])
  onWindowMouseMove(event: MouseEvent): void {
    if (this.panDrag) {
      const dx = event.clientX - this.panDrag.start.x;
      const dy = event.clientY - this.panDrag.start.y;
      this.state.setPan({
        x: this.panDrag.pan0.x + dx,
        y: this.panDrag.pan0.y + dy,
      });
      return;
    }
    if (this.nodeDrag) {
      const z = this.state.zoom();
      const dx = (event.clientX - this.nodeDrag.start.x) / z;
      const dy = (event.clientY - this.nodeDrag.start.y) / z;
      this.state.moveNodeLive(this.nodeDrag.nodeId, {
        x: this.nodeDrag.initialPos.x + dx,
        y: this.nodeDrag.initialPos.y + dy,
      });
      if (Math.abs(dx) + Math.abs(dy) > 4) {
        this.nodeDrag.moved = true;
      }
      return;
    }
    if (this.pendingEdge()) {
      const pos = this.toCanvasCoords(event);
      this.pendingEdge.update((v) => (v ? { ...v, cursor: pos } : v));
    }
  }

  @HostListener('window:mouseup', ['$event'])
  onWindowMouseUp(event: MouseEvent): void {
    if (this.panDrag) {
      this.panDrag = null;
    }
    if (this.nodeDrag) {
      if (this.nodeDrag.moved) {
        const final = this.state
          .nodes()
          .find((n) => n.id === this.nodeDrag!.nodeId);
        if (final) {
          // Commit the move through the undo-tracked path.
          this.state.moveNode(this.nodeDrag.nodeId, final.position ?? { x: 0, y: 0 });
        }
      }
      this.nodeDrag = null;
    }
    if (this.pendingEdge()) {
      // Mouseup outside a target → cancel.
      this.pendingEdge.set(null);
    }
  }

  onWheel(event: WheelEvent): void {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    const delta = event.deltaY < 0 ? 1.1 : 1 / 1.1;
    const z0 = this.state.zoom();
    const z1 = Math.min(4, Math.max(0.25, z0 * delta));
    if (z1 === z0) return;
    // Zoom toward the cursor — keep the canvas point under the cursor
    // stationary.
    const point = this.toCanvasCoords(event);
    const p0 = this.state.pan();
    const dx = point.x - (point.x - p0.x) * (z1 / z0);
    const dy = point.y - (point.y - p0.y) * (z1 / z0);
    this.state.setZoom(z1);
    this.state.setPan({ x: dx, y: dy });
  }


  // --- Node drag (move) -----------------------------------------------

  onNodeMouseDown(payload: { nodeId: string; event: MouseEvent }): void {
    payload.event.stopPropagation();
    const node = this.nodeById().get(payload.nodeId);
    if (!node) return;
    this.nodeDrag = {
      nodeId: payload.nodeId,
      start: { x: payload.event.clientX, y: payload.event.clientY },
      initialPos: { ...(node.position ?? { x: 0, y: 0 }) },
      moved: false,
    };
  }

  onNodeSelect(nodeId: string): void {
    this.state.selectNode(nodeId);
  }


  // --- Edge drag (connect) --------------------------------------------

  onOutputPortDown(payload: {
    nodeId: string;
    portLabel: string | null;
    event: MouseEvent;
  }): void {
    const node = this.nodeById().get(payload.nodeId);
    if (!node) return;
    const outputs = getNodeType(node.type)?.outputs ?? [];
    const idx = Math.max(
      0,
      outputs.findIndex((o) => (o.label ?? null) === payload.portLabel),
    );
    const sx =
      (node.position?.x ?? 0) +
      this.computeOutputPortX(idx, outputs.length);
    const sy = (node.position?.y ?? 0) + NODE_HEIGHT;
    const cursor = this.toCanvasCoords(payload.event);
    this.pendingEdge.set({
      sourceNodeId: payload.nodeId,
      sourcePortLabel: payload.portLabel,
      start: { x: sx, y: sy },
      cursor,
    });
  }

  onInputPortUp(payload: { nodeId: string; event: MouseEvent }): void {
    const pending = this.pendingEdge();
    if (!pending) return;
    if (pending.sourceNodeId === payload.nodeId) {
      this.pendingEdge.set(null);
      return;
    }
    this.state.addEdge(
      pending.sourceNodeId,
      payload.nodeId,
      pending.sourcePortLabel,
    );
    this.pendingEdge.set(null);
  }

  private computeOutputPortX(index: number, total: number): number {
    if (total <= 1) return NODE_WIDTH / 2;
    const usable = NODE_WIDTH - 40;
    const step = usable / (total - 1);
    return 20 + step * index;
  }


  // --- Drop from palette ----------------------------------------------

  onDragOver(event: DragEvent): void {
    if (event.dataTransfer?.types.includes('text/workflow-node-type')) {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'copy';
    }
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    const type = event.dataTransfer?.getData('text/workflow-node-type');
    if (!type) return;
    const pos = this.toCanvasCoords(event);
    // Centre the node on the cursor.
    this.state.addNode(type, {
      x: pos.x - NODE_WIDTH / 2,
      y: pos.y - NODE_HEIGHT / 2,
    });
  }


  // --- Camera helpers + keyboard --------------------------------------

  fitToView(): void {
    const svg = this.canvasRoot?.nativeElement;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    this.state.fitToView({ width: rect.width, height: rect.height });
  }

  resetZoom(): void {
    this.state.setZoom(1);
    this.state.setPan({ x: 0, y: 0 });
  }

  autoLayout(): void {
    void this.doAutoLayout();
  }

  private async doAutoLayout(): Promise<void> {
    const dagre = await import('dagre');
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 100 });
    g.setDefaultEdgeLabel(() => ({}));
    for (const node of this.state.nodes()) {
      g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
    }
    for (const edge of this.state.edges()) {
      g.setEdge(edge.source, edge.target);
    }
    dagre.layout(g);
    for (const node of this.state.nodes()) {
      const pos = g.node(node.id);
      if (pos) {
        // dagre's coordinates centre the node; shift to top-left.
        this.state.moveNodeLive(node.id, {
          x: pos.x - NODE_WIDTH / 2,
          y: pos.y - NODE_HEIGHT / 2,
        });
      }
    }
    // Commit a single snapshot for the whole layout pass.
    const first = this.state.nodes()[0];
    if (first) {
      this.state.moveNode(first.id, first.position ?? { x: 0, y: 0 });
    }
    this.fitToView();
  }

  @HostListener('window:keydown', ['$event'])
  onWindowKeyDown(event: KeyboardEvent): void {
    if ((event.target as HTMLElement | null)?.tagName === 'INPUT') return;
    const cmd = event.ctrlKey || event.metaKey;
    if (cmd && event.key === 'z' && !event.shiftKey) {
      event.preventDefault();
      this.state.undo();
    } else if (
      (cmd && event.key === 'y') ||
      (cmd && event.shiftKey && event.key.toLowerCase() === 'z')
    ) {
      event.preventDefault();
      this.state.redo();
    } else if (cmd && event.key === 's') {
      event.preventDefault();
      if (this.state.dirty()) this.save();
    } else if (
      event.key === 'Delete' &&
      this.state.selectedNodeId() !== null
    ) {
      const id = this.state.selectedNodeId();
      if (id) this.state.deleteNode(id);
    }
  }


  // --- Coord transforms -----------------------------------------------

  private toCanvasCoords(event: MouseEvent | DragEvent): CursorPoint {
    const svg = this.canvasRoot?.nativeElement;
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    const pan = this.state.pan();
    const z = this.state.zoom();
    const clientX = (event as MouseEvent).clientX;
    const clientY = (event as MouseEvent).clientY;
    return {
      x: (clientX - rect.left - pan.x) / z,
      y: (clientY - rect.top - pan.y) / z,
    };
  }

  // --- Right-drawer helpers (Step 15 fills the body) ------------------

  readonly selectedNode = computed(() => this.state.selectedNode());
  readonly statuses: WorkflowStatus[] = ['draft', 'active', 'paused', 'archived'];
}

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
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { ConfirmDialogService } from '../../shared/confirm-dialog/confirm-dialog.service';
import { CanvasNode, CanvasStateService } from './canvas-state.service';
import { ContextMenuComponent, ContextMenuItem } from './context-menu.component';
import { WorkflowEdgeComponent } from './edge.component';
import { ImportModalComponent } from './import-modal.component';
import { NodeEditorComponent } from './node-editor.component';
import { NodePaletteComponent } from './node-palette.component';
import { NODE_HEIGHT, NODE_WIDTH, WorkflowNodeComponent } from './node.component';
import { getNodeType } from './node-type-registry';
import { SaveChangeNoteModalComponent } from './save-change-note.modal.component';
import { ScheduleConfigModalComponent } from './schedule-config-modal.component';
import { SchedulesDrawerComponent } from './schedules-drawer.component';
import { VersionHistoryDrawerComponent } from './version-history-drawer.component';
import {
  Schedule,
  WorkflowExportBody,
  WorkflowGraph,
  WorkflowRead,
  WorkflowStatus,
  WorkflowTestFireResponse,
  WorkflowVersionDetail,
  WorkflowsApiService,
} from '../workflows-api.service';
import { WorkflowStatusBadgeComponent } from '../workflow-status-badge.component';
import { ABPairModalComponent } from '../ab/ab-pair-modal.component';
import { ABStatsBannerComponent } from '../ab/ab-stats-banner.component';

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
    ContextMenuComponent,
    ImportModalComponent,
    NodeEditorComponent,
    NodePaletteComponent,
    SaveChangeNoteModalComponent,
    ScheduleConfigModalComponent,
    SchedulesDrawerComponent,
    VersionHistoryDrawerComponent,
    WorkflowNodeComponent,
    WorkflowEdgeComponent,
    WorkflowStatusBadgeComponent,
    ABPairModalComponent,
    ABStatsBannerComponent,
  ],
  templateUrl: './workflow-canvas.page.html',
})
export class WorkflowCanvasPageComponent {
  readonly state = inject(CanvasStateService);
  private readonly api = inject(WorkflowsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);
  private readonly confirmDialog = inject(ConfirmDialogService);

  @ViewChild('canvasRoot', { static: false })
  canvasRoot!: ElementRef<SVGSVGElement>;

  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);
  readonly testFireBusy = signal(false);
  readonly testFireTrace = signal<WorkflowTestFireResponse | null>(null);

  // Mobile-only overlay toggles. On desktop (md+) both panels are always
  // visible in-flow; on mobile they slide over the canvas.
  readonly mobilePaletteOpen = signal(false);
  readonly mobileInspectorOpen = signal(false);

  toggleMobilePalette(): void {
    this.mobilePaletteOpen.update((v) => !v);
    if (this.mobilePaletteOpen()) this.mobileInspectorOpen.set(false);
  }
  toggleMobileInspector(): void {
    this.mobileInspectorOpen.update((v) => !v);
    if (this.mobileInspectorOpen()) this.mobilePaletteOpen.set(false);
  }
  closeMobileOverlays(): void {
    this.mobilePaletteOpen.set(false);
    this.mobileInspectorOpen.set(false);
  }

  // Desktop-only sidebar collapse toggles. Node palette + right
  // inspector each eat ~300-440px of screen; collapsing either gives
  // the canvas back the space. Mobile ignores these (mobile uses the
  // slide-over toggles instead). Persist to localStorage so the
  // operator's preference sticks across canvas visits.
  readonly paletteCollapsed = signal(this._readCollapsePref('palette'));
  readonly inspectorCollapsed = signal(this._readCollapsePref('inspector'));
  togglePaletteCollapsed(): void {
    this.paletteCollapsed.update((v) => !v);
    this._writeCollapsePref('palette', this.paletteCollapsed());
  }
  toggleInspectorCollapsed(): void {
    this.inspectorCollapsed.update((v) => !v);
    this._writeCollapsePref('inspector', this.inspectorCollapsed());
  }
  private _readCollapsePref(key: 'palette' | 'inspector'): boolean {
    try {
      return localStorage.getItem(`wf-canvas-${key}-collapsed`) === '1';
    } catch {
      return false;
    }
  }
  private _writeCollapsePref(key: 'palette' | 'inspector', value: boolean): void {
    try {
      localStorage.setItem(`wf-canvas-${key}-collapsed`, value ? '1' : '0');
    } catch {
      // Storage disabled (Safari private mode) — silently ignore.
    }
  }

  // tasks/workflow-scheduling Step 4 — schedules drawer, opened by
  // the header calendar-clock button. Mutually exclusive with the
  // version drawer (both share the same right-side inspector slot).
  readonly showSchedulesDrawer = signal(false);

  // Schedule config modal — hoisted to top-level so `position: fixed`
  // is viewport-relative. The right-side aside uses `transform` for
  // its slide-over, which would otherwise trap the modal inside
  // the aside's 440px bounds.
  readonly scheduleModalOpen = signal(false);
  readonly scheduleModalEditing = signal<Schedule | null>(null);
  readonly schedulesRefreshToken = signal(0);
  onScheduleConfigOpen(editing: Schedule | null): void {
    this.scheduleModalEditing.set(editing);
    this.scheduleModalOpen.set(true);
  }
  onScheduleConfigClose(): void {
    this.scheduleModalOpen.set(false);
    this.scheduleModalEditing.set(null);
  }
  onScheduleConfigSaved(_saved: Schedule): void {
    this.onScheduleConfigClose();
    this.schedulesRefreshToken.update((n) => n + 1);
  }
  toggleSchedulesDrawer(): void {
    this.showSchedulesDrawer.update((v) => !v);
    if (this.showSchedulesDrawer()) {
      this.showVersionDrawer.set(false);
    }
  }
  closeSchedulesDrawer(): void {
    this.showSchedulesDrawer.set(false);
  }

  // Step 17 — version history + import/export.
  readonly showVersionDrawer = signal(false);
  readonly viewingVersion = signal<number | null>(null);
  private previewBackup: WorkflowGraph | null = null;
  readonly showImportModal = signal(false);
  readonly importBusy = signal(false);
  readonly showChangeNoteModal = signal(false);

  // Step 18 — full workflow record (for A/B affordances). Refreshed on
  // every successful load + after pair/unpair.
  readonly loadedWorkflow = signal<WorkflowRead | null>(null);
  readonly showPairModal = signal(false);

  readonly isABPaired = computed(() => this.loadedWorkflow()?.ab_paired_workflow_id != null);
  readonly isABDecided = computed(() => this.loadedWorkflow()?.ab_test_decided_at != null);

  // Camera + edge-drag local state.
  readonly pendingEdge = signal<PendingEdge | null>(null);
  private panDrag: { start: CursorPoint; pan0: CursorPoint } | null = null;
  private nodeDrag: {
    nodeId: string;
    start: CursorPoint;
    initialPos: CursorPoint;
    moved: boolean;
  } | null = null;

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
      if (this.state.dirty() && this.state.status() === 'draft' && this.state.workflowId()) {
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
    this.destroyRef.onDestroy(() => window.removeEventListener('beforeunload', beforeUnload));
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
          this.loadedWorkflow.set(workflow);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Could not load workflow.');
          this.loading.set(false);
        },
      });
  }

  save(opts: { silent?: boolean; changeNote?: string } = {}): void {
    // Client-side pre-flight — mirrors the backend graph rules so the
    // operator sees plain-language guidance instantly instead of a
    // round-trip 422. Silent auto-save aborts quietly; explicit Save
    // surfaces the message in the header error banner AND a toast.
    const preflight = this.preflightGraph();
    if (preflight) {
      if (!opts.silent) {
        this.error.set(preflight);
        this.toast.warn("Can't save yet", { subtitle: preflight });
      }
      return;
    }

    // Step 17 — explicit Save Draft on an existing workflow pops the
    // change-note modal so the version row gets a meaningful label.
    // Auto-save (`silent: true`) and brand-new workflows skip it.
    const id = this.state.workflowId();
    if (id && !opts.silent && opts.changeNote === undefined && this.state.dirty()) {
      this.showChangeNoteModal.set(true);
      return;
    }
    this.flushSave(opts);
  }

  /** Fast client-side check that mirrors the cheap subset of the
   *  backend's `validate_graph`. Catches the three failures beginners
   *  hit constantly (empty graph, missing trigger, unconnected nodes)
   *  so we can show plain-language guidance without a network trip.
   *  Deeper checks (registry lookups, condition AST, template refs)
   *  still land server-side. Returns null when the graph looks OK. */
  private preflightGraph(): string | null {
    const nodes = this.state.nodes();
    if (nodes.length === 0) {
      return this.friendlyGraphError('workflow.graph must contain at least one node');
    }
    const triggers = nodes.filter((n) => (n.type || '').startsWith('trigger'));
    if (triggers.length === 0) {
      return this.friendlyGraphError('workflow.graph must contain a trigger node');
    }
    if (triggers.length > 1) {
      return this.friendlyGraphError(
        `workflow.graph must contain exactly one trigger node; found ${triggers.length}`,
      );
    }
    const trigger = triggers[0];
    const eventType = (trigger.config as Record<string, unknown> | undefined)?.['event_type'];
    if (typeof eventType !== 'string' || eventType.trim() === '') {
      return this.friendlyGraphError(
        `trigger node '${trigger.id}' missing non-empty config.event_type`,
      );
    }
    // Reachability from the trigger. Wait-for-event `timeout` edges may
    // back-flow, so we skip them for the forward walk (matches
    // graph.py's rule).
    const edges = this.state.edges();
    const forward = new Map<string, string[]>();
    for (const e of edges) {
      if (e.label === 'timeout') continue;
      const list = forward.get(e.source) ?? [];
      list.push(e.target);
      forward.set(e.source, list);
    }
    const reachable = new Set<string>([trigger.id]);
    const stack: string[] = [trigger.id];
    while (stack.length) {
      const current = stack.pop() as string;
      for (const next of forward.get(current) ?? []) {
        if (!reachable.has(next)) {
          reachable.add(next);
          stack.push(next);
        }
      }
    }
    const unreachable = nodes.filter((n) => !reachable.has(n.id));
    if (unreachable.length > 0) {
      return this.friendlyGraphError(
        `workflow.graph has unreachable nodes: ${unreachable.map((n) => n.id).join(', ')}`,
      );
    }
    return null;
  }

  private flushSave(opts: { silent?: boolean; changeNote?: string } = {}): void {
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

    const obs = id ? this.api.patch(id, patchBody) : this.api.create({ name, graph });

    obs.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (workflow) => {
        const wasCreate = !id;
        this.state.setWorkflowId(workflow.id);
        this.state.setStatus(workflow.status);
        this.state.clearDirty();
        this.loadedWorkflow.set(workflow);
        this.saving.set(false);
        if (!opts.silent) {
          this.toast.success(wasCreate ? 'Workflow created' : 'Workflow saved');
        }
        if (wasCreate && !opts.silent) {
          // Created — swap the URL so subsequent refreshes load the
          // workflow rather than re-creating blanks.
          this.router.navigate(['/user/workflows', workflow.id], { replaceUrl: true });
        }
      },
      error: (err: HttpErrorResponse) => {
        const friendly = this.friendlyHttpError(err, 'Save failed.');
        this.error.set(friendly);
        this.saving.set(false);
        if (!opts.silent) {
          this.toast.error('Save failed', { subtitle: friendly });
        }
      },
    });
  }

  /** Turns an HttpErrorResponse into a plain-language string for the
   *  banner + toast. Handles the three common non-graph failure modes
   *  (401 session expired, 403 missing permission, network offline)
   *  before falling back to the graph-specific translator. */
  private friendlyHttpError(err: HttpErrorResponse, fallback: string): string {
    if (err.status === 401) {
      return 'Session expired — please sign in again.';
    }
    if (err.status === 403) {
      return extractApiError(err) ?? "You don't have permission to do that.";
    }
    if (err.status === 0) {
      return 'Network unreachable — check your connection and try again.';
    }
    return this.friendlyGraphError(extractApiError(err) ?? fallback);
  }

  /** Rewrites low-level backend graph-validation reasons into
   *  plain-language guidance the operator can act on. Falls through
   *  to the raw message when we don't recognise the shape. */
  private friendlyGraphError(reason: string): string {
    const lower = reason.toLowerCase();
    if (lower.includes('unreachable node')) {
      return "Some nodes aren't connected. Drag from the trigger's output port (bottom) to each node's input port (top) so every node is reachable from the trigger.";
    }
    if (lower.includes('must contain a trigger node')) {
      return 'Add a Trigger node from the palette — every workflow needs one entry point.';
    }
    if (lower.includes('exactly one trigger node')) {
      return 'A workflow can only have one Trigger node. Remove the extras.';
    }
    if (lower.includes('missing non-empty config.event_type')) {
      return 'Open the Trigger node and pick an event (e.g. "Contact created") before saving.';
    }
    if (lower.includes('must contain at least one node')) {
      return 'Add at least one node (start with a Trigger from the palette) before saving.';
    }
    if (lower.includes('contains a cycle')) {
      return 'The graph contains a loop. Only wait-for-event timeout edges may loop back — remove the cyclic edge.';
    }
    return reason;
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
    if (this.showVersionDrawer()) {
      // Mutual exclusion with the schedules drawer — both share the
      // same inspector slot.
      this.showSchedulesDrawer.set(false);
    }
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
        error: (err: HttpErrorResponse) => this.error.set(extractApiError(err) ?? 'Export failed.'),
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

  confirmImport(payload: { body: WorkflowExportBody; name: string | null }): void {
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

  async activate(): Promise<void> {
    const id = this.state.workflowId();
    if (!id) return;
    if (this.state.dirty()) {
      const ok = await this.confirmDialog.ask({
        title: 'Save unsaved changes first?',
        body: 'The workflow has unsaved edits. Activating without saving would use the previously-persisted graph.',
        confirmLabel: 'Save & activate',
      });
      if (!ok) return;
      this.save();
    }
    this.api
      .activate(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (workflow) => {
          this.state.setStatus(workflow.status);
          this.toast.success('Workflow activated', {
            subtitle: 'New matching events will now enroll contacts.',
          });
        },
        error: (err: HttpErrorResponse) => {
          const friendly = this.friendlyHttpError(err, 'Activate failed.');
          this.error.set(friendly);
          this.toast.error('Activate failed', { subtitle: friendly });
        },
      });
  }

  pause(): void {
    const id = this.state.workflowId();
    if (!id) return;
    this.api
      .pause(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (workflow) => {
          this.state.setStatus(workflow.status);
          this.toast.info('Workflow paused', {
            subtitle: 'No new enrollments until you reactivate.',
          });
        },
        error: (err: HttpErrorResponse) => {
          const friendly = this.friendlyHttpError(err, 'Pause failed.');
          this.error.set(friendly);
          this.toast.error('Pause failed', { subtitle: friendly });
        },
      });
  }

  async discard(): Promise<void> {
    if (!this.state.dirty()) return;
    const ok = await this.confirmDialog.ask({
      title: 'Discard unsaved changes?',
      body: 'The canvas will revert to the last saved state. This cannot be undone.',
      confirmLabel: 'Discard changes',
      danger: true,
    });
    if (!ok) return;
    const id = this.state.workflowId();
    if (id) {
      this.loadExisting(id);
    } else {
      this.state.loadBlank(this.state.name() || 'Untitled workflow');
    }
  }

  async testFire(): Promise<void> {
    const id = this.state.workflowId();
    if (!id) return;
    if (this.state.dirty()) {
      const ok = await this.confirmDialog.ask({
        title: 'Save before test-firing?',
        body: 'The dry-run uses the persisted graph, so unsaved edits won’t be included until you save.',
        confirmLabel: 'Save & test fire',
      });
      if (!ok) return;
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
  onWindowMouseUp(_event: MouseEvent): void {
    if (this.panDrag) {
      this.panDrag = null;
    }
    if (this.nodeDrag) {
      if (this.nodeDrag.moved) {
        const final = this.state.nodes().find((n) => n.id === this.nodeDrag!.nodeId);
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

  // --- Right-click context menu ---------------------------------------

  // Open menu descriptor. `nodeId` null → the empty-canvas menu.
  // `canvas` is the click point in canvas coords (used for Paste).
  readonly contextMenu = signal<{
    x: number;
    y: number;
    nodeId: string | null;
    canvas: CursorPoint;
  } | null>(null);

  // Single-node clipboard (type + config) shared by Copy → Paste.
  private readonly clipboard = signal<{ type: string; config: Record<string, unknown> } | null>(
    null,
  );

  readonly contextMenuItems = computed<ContextMenuItem[]>(() => {
    const ctx = this.contextMenu();
    if (!ctx) return [];
    if (ctx.nodeId) {
      const hasEdges = this.state
        .edges()
        .some((e) => e.source === ctx.nodeId || e.target === ctx.nodeId);
      return [
        { id: 'edit', label: 'Edit', icon: 'Pencil' },
        { id: 'duplicate', label: 'Duplicate', icon: 'Files' },
        { id: 'copy', label: 'Copy', icon: 'Copy' },
        { id: 'disconnect', label: 'Disconnect', icon: 'Scissors', disabled: !hasEdges },
        { id: 'delete', label: 'Delete', icon: 'Trash2', danger: true, separatorBefore: true },
      ];
    }
    return [
      { id: 'paste', label: 'Paste', icon: 'ClipboardPaste', disabled: this.clipboard() === null },
      { id: 'fit', label: 'Fit to view', icon: 'Maximize2', separatorBefore: true },
      { id: 'reset', label: 'Reset zoom', icon: 'RotateCcw' },
      { id: 'autolayout', label: 'Auto-layout', icon: 'LayoutGrid' },
    ];
  });

  onNodeContextMenu(payload: { nodeId: string; x: number; y: number }): void {
    const node = this.nodeById().get(payload.nodeId);
    this.state.selectNode(payload.nodeId);
    this.contextMenu.set({
      x: payload.x,
      y: payload.y,
      nodeId: payload.nodeId,
      canvas: { ...(node?.position ?? { x: 0, y: 0 }) },
    });
  }

  onCanvasContextMenu(event: MouseEvent): void {
    event.preventDefault();
    this.state.selectNode(null);
    this.contextMenu.set({
      x: event.clientX,
      y: event.clientY,
      nodeId: null,
      canvas: this.toCanvasCoords(event),
    });
  }

  closeContextMenu(): void {
    this.contextMenu.set(null);
  }

  async onContextMenuSelect(actionId: string): Promise<void> {
    const ctx = this.contextMenu();
    if (!ctx) return;
    const nodeId = ctx.nodeId;
    switch (actionId) {
      case 'edit':
        if (nodeId) this.state.selectNode(nodeId);
        break;
      case 'duplicate':
        if (nodeId) this.state.duplicateNode(nodeId);
        break;
      case 'copy':
        if (nodeId) {
          const node = this.nodeById().get(nodeId);
          if (node) {
            this.clipboard.set({
              type: node.type,
              config: { ...((node.config as Record<string, unknown>) ?? {}) },
            });
          }
        }
        break;
      case 'disconnect':
        if (nodeId) {
          for (const e of this.state.edges()) {
            if (e.source === nodeId || e.target === nodeId) this.state.deleteEdge(e.id);
          }
        }
        break;
      case 'delete':
        if (!nodeId) break;
        if (
          await this.confirmDialog.ask({
            title: 'Delete this node?',
            body: 'The node and every edge attached to it will be removed. You can undo with Ctrl+Z.',
            confirmLabel: 'Delete',
            danger: true,
          })
        ) {
          this.state.deleteNode(nodeId);
        }
        break;
      case 'paste': {
        const clip = this.clipboard();
        if (clip) {
          this.state.addNode(
            clip.type,
            { x: ctx.canvas.x - NODE_WIDTH / 2, y: ctx.canvas.y - NODE_HEIGHT / 2 },
            { config: clip.config },
          );
        }
        break;
      }
      case 'fit':
        this.fitToView();
        break;
      case 'reset':
        this.resetZoom();
        break;
      case 'autolayout':
        this.autoLayout();
        break;
    }
  }

  // --- Edge drag (connect) --------------------------------------------

  onOutputPortDown(payload: { nodeId: string; portLabel: string | null; event: MouseEvent }): void {
    const node = this.nodeById().get(payload.nodeId);
    if (!node) return;
    const outputs = getNodeType(node.type)?.outputs ?? [];
    const idx = Math.max(
      0,
      outputs.findIndex((o) => (o.label ?? null) === payload.portLabel),
    );
    const sx = (node.position?.x ?? 0) + this.computeOutputPortX(idx, outputs.length);
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
    this.state.addEdge(pending.sourceNodeId, payload.nodeId, pending.sourcePortLabel);
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
    // Always accept the drop — some browsers (Firefox, older Chromium
    // profiles) don't expose custom MIME types on `dataTransfer.types`
    // during dragover, only during drop. Gating preventDefault on the
    // presence check made those browsers silently reject the drop
    // and leave the palette dragging nothing onto the canvas.
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'copy';
    }
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    // Filter here instead of dragover — `getData` on drop is reliable
    // across browsers. If the payload isn't a workflow node type, bail
    // silently so unrelated drops (e.g. text from another app) don't
    // create garbage nodes.
    const type = event.dataTransfer?.getData('text/workflow-node-type');
    if (!type) return;
    const pos = this.toCanvasCoords(event);
    // Centre the node on the cursor.
    this.state.addNode(type, {
      x: pos.x - NODE_WIDTH / 2,
      y: pos.y - NODE_HEIGHT / 2,
    });
  }

  /** Tap-to-add fallback: touch devices can't fire HTML5 drag events,
   *  so mobile users tap a palette item and we place the node at the
   *  current viewport centre in canvas coords. Also closes the mobile
   *  palette overlay so the freshly-added node is visible. */
  onPaletteTap(type: string): void {
    if (!type) return;
    const svg = this.canvasRoot?.nativeElement;
    const rect = svg?.getBoundingClientRect();
    let centreClient = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    if (rect) {
      centreClient = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    }
    // Translate the centre client-pt into canvas coords through the
    // same helper the drop handler uses (respects pan + zoom).
    const pseudoEvent = { clientX: centreClient.x, clientY: centreClient.y } as DragEvent;
    const pos = this.toCanvasCoords(pseudoEvent);
    this.state.addNode(type, {
      x: pos.x - NODE_WIDTH / 2,
      y: pos.y - NODE_HEIGHT / 2,
    });
    // Close the mobile palette overlay so the new node isn't covered.
    this.mobilePaletteOpen.set(false);
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
    } else if (event.key === 'Delete' && this.state.selectedNodeId() !== null) {
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

  // --- Step 18 — A/B pairing + banner refresh -------------------------

  openPairModal(): void {
    if (!this.loadedWorkflow()) return;
    this.showPairModal.set(true);
  }

  cancelPair(): void {
    this.showPairModal.set(false);
  }

  confirmPair(workflow: WorkflowRead): void {
    this.showPairModal.set(false);
    this.loadedWorkflow.set(workflow);
    this.state.setStatus(workflow.status);
  }

  async unpairAB(): Promise<void> {
    const id = this.state.workflowId();
    if (!id) return;
    const ok = await this.confirmDialog.ask({
      title: 'Cancel this A/B test?',
      body: 'Both workflows revert to standalone — no winner will be recorded.',
      confirmLabel: 'Cancel A/B test',
      danger: true,
    });
    if (!ok) return;
    this.api
      .unpairAB(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (workflow) => {
          this.loadedWorkflow.set(workflow);
          this.state.setStatus(workflow.status);
        },
        error: (err) => this.error.set(extractApiError(err) ?? 'Unpair failed.'),
      });
  }
}

import { CommonModule } from '@angular/common';
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
import { MatSnackBar } from '@angular/material/snack-bar';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { ConfirmDialogComponent } from '../../shared/confirm-dialog/confirm-dialog.component';
import { ChatbotsApiService, TriggerConfig } from '../chatbots-api.service';
import { CanvasNode, CanvasStateService } from './canvas-state.service';
import { NodeConfigFormComponent } from './node-config-form/node-config-form.component';
import { NodeTypeMeta, getNodeType } from './node-type-registry';
import { ChatbotMinimapComponent } from './minimap/minimap.component';
import { ChatbotPaletteComponent } from './palette/palette.component';
import { ChatbotTestFireModalComponent } from './test-fire-modal/test-fire-modal.component';
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
    ChatbotTestFireModalComponent,
    ChatbotMinimapComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './builder.page.html',
})
export class ChatbotBuilderPageComponent {
  private readonly api = inject(ChatbotsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly snackBar = inject(MatSnackBar);
  readonly canvas = inject(CanvasStateService);

  readonly loading = signal<boolean>(true);
  readonly error = signal<string | null>(null);
  readonly triggerModalOpen = signal<boolean>(false);
  readonly deleteNodeId = signal<string | null>(null);
  readonly testModalOpen = signal<boolean>(false);
  readonly helpModalOpen = signal<boolean>(false);
  readonly publishConfirmOpen = signal<boolean>(false);

  /** Right-click node menu — the id of the node whose context menu
   *  is open, plus screen coordinates where the operator clicked. */
  readonly contextMenuNodeId = signal<string | null>(null);
  readonly contextMenuPos = signal<{ x: number; y: number }>({ x: 0, y: 0 });

  /** Node search box (visible pill at top of canvas). Empty string
   *  hides the dropdown. */
  readonly searchQuery = signal<string>('');

  /** Active drag gesture, if any. Set on node-header mousedown, read
   *  by the document-level mousemove listener, cleared on mouseup. */
  private dragState: {
    nodeId: string;
    startMouseX: number;
    startMouseY: number;
    startPosX: number;
    startPosY: number;
    moved: boolean;
  } | null = null;

  /** Set true for one tick after a drag ends so the trailing click
   *  (browsers fire click on the mousedown target after mouseup) is
   *  swallowed by `selectNode` — otherwise dragging a node would
   *  also select it, or worse, complete a pending click-to-connect
   *  gesture. */
  private suppressNextClick = false;

  readonly bot = this.canvas.bot;
  readonly nodes = this.canvas.nodes;
  readonly edges = this.canvas.edges;
  readonly triggerConfig = this.canvas.triggerConfig;
  readonly selectedNodeId = this.canvas.selectedNodeId;
  readonly dirty = this.canvas.dirty;
  readonly saving = this.canvas.saving;
  readonly pendingSourceId = this.canvas.pendingSourceId;
  readonly triggerPosition = this.canvas.triggerPosition;
  readonly zoom = this.canvas.zoom;
  readonly paletteCollapsed = this.canvas.paletteCollapsed;
  readonly cardWidth = this.canvas.cardWidth;

  readonly zoomPercent = computed(() => Math.round(this.zoom() * 100));

  /** Active card-resize gesture, if any. Started from the bottom-right
   *  corner grip on the trigger card or any node — the source id is
   *  incidental since `cardWidth` is a single global signal, but we
   *  keep it for symmetry with the drag-to-move gesture. */
  private cardResizeStart: { startX: number; startWidth: number } | null = null;

  onCardResizeMouseDown(evt: MouseEvent): void {
    if (evt.button !== 0) return;
    evt.preventDefault();
    evt.stopPropagation();
    this.cardResizeStart = {
      startX: evt.clientX,
      startWidth: this.canvas.cardWidth(),
    };
  }

  /** Layout constants matching the template. Card widths (trigger +
   *  nodes) are shared via the `cardWidth` signal so a resize on any
   *  card grip rescales the whole graph consistently. */
  private readonly CANVAS_PAD = 24;
  private readonly TRIGGER_LEFT = this.CANVAS_PAD;
  private readonly TRIGGER_TOP = this.CANVAS_PAD;
  private readonly TRIGGER_HEIGHT = 118;
  private readonly NODE_HEADER_H = 44;
  /** Gap between the trigger card's right edge and the first node
   *  column. Node positions are relative to this anchor. */
  private readonly TRIGGER_GAP = 60;

  /** X anchor of the node column — moves with the shared cardWidth
   *  so nodes never overlap the trigger. */
  nodeLeftOffset(): number {
    return this.CANVAS_PAD + this.cardWidth() + this.TRIGGER_GAP;
  }

  /** Where each node's LEFT (input) port lives, absolute canvas
   *  coordinates. */
  inputPortPos(node: CanvasNode): { x: number; y: number } {
    return {
      x: this.nodeLeftOffset() + node.position.x,
      y: node.position.y + this.NODE_HEADER_H / 2,
    };
  }

  /** Where each node's RIGHT (output) port lives.
   *
   *  For `labeled` / `single` topology the ports are stacked below
   *  the header at 22 px rows.
   *
   *  For `dynamic` topology (text_button / media_button) the ports
   *  are rendered INSIDE the button rows in the config form (Pabbly-
   *  style), so we compute Y from the buttons-area start plus the
   *  button row index. Constants are approximate because the schema
   *  form has variable content above buttons, but visually the SVG
   *  edge lands within a few pixels of the actual port dot. */
  outputPortPos(node: CanvasNode, labelIndex = 0): { x: number; y: number } {
    const x = this.nodeLeftOffset() + node.position.x + this.cardWidth();
    if (node.type === 'text_button') {
      return {
        x,
        y: node.position.y + 198 + labelIndex * 46,
      };
    }
    if (node.type === 'media_button') {
      return {
        x,
        y: node.position.y + 322 + labelIndex * 46,
      };
    }
    return {
      x,
      y: node.position.y + this.NODE_HEADER_H / 2 + labelIndex * 22,
    };
  }

  triggerPortPos(): { x: number; y: number } {
    // Trigger card is absolutely positioned at CANVAS_PAD + user
    // drag offset (`triggerPosition` — session-only). Port sits on
    // the right edge, centered vertically.
    const pos = this.triggerPosition();
    return {
      x: this.TRIGGER_LEFT + pos.x + this.cardWidth(),
      y: this.TRIGGER_TOP + pos.y + this.TRIGGER_HEIGHT / 2,
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

  /** Per-node list of output ports. `single` topology → one unlabelled
   *  "next" port. `labeled` → one port per meta.labels entry (fixed).
   *  `dynamic` → one port per config-driven item (text_button /
   *  media_button = per button, list = per row across sections). Each
   *  port's `label` is what gets persisted on the edge — for dynamic
   *  nodes we use the button/row `id` so the backend engine can look
   *  up the matched button reliably. */
  outputPortsFor(node: CanvasNode): { label: string | null; title: string }[] {
    const meta = getNodeType(node.type);
    if (!meta) return [{ label: null, title: 'next' }];
    if (meta.outputs === 'single') return [{ label: null, title: 'next' }];
    if (meta.outputs === 'labeled') {
      return (meta.labels ?? []).map((l) => ({ label: l, title: l }));
    }
    // dynamic — read the config to enumerate ports.
    const cfg = node.config ?? {};
    if (node.type === 'text_button' || node.type === 'media_button') {
      const buttons = Array.isArray(cfg['buttons']) ? (cfg['buttons'] as unknown[]) : [];
      const ports = buttons.map((b, i) => {
        const row = (b ?? {}) as Record<string, unknown>;
        const id = typeof row['id'] === 'string' ? (row['id'] as string) : `btn_${i + 1}`;
        const title = typeof row['title'] === 'string' ? (row['title'] as string) : id;
        return { label: id, title: title || id };
      });
      // Always expose a fallback "default" port so a text_button with no
      // buttons yet is still connectable.
      return ports.length ? ports : [{ label: null, title: 'next' }];
    }
    if (node.type === 'list') {
      const sections = Array.isArray(cfg['sections']) ? (cfg['sections'] as unknown[]) : [];
      const rows: { label: string; title: string }[] = [];
      sections.forEach((s, si) => {
        const section = (s ?? {}) as Record<string, unknown>;
        const secRows = Array.isArray(section['rows']) ? (section['rows'] as unknown[]) : [];
        secRows.forEach((r, ri) => {
          const row = (r ?? {}) as Record<string, unknown>;
          const id =
            typeof row['id'] === 'string' ? (row['id'] as string) : `row_${si + 1}_${ri + 1}`;
          const title = typeof row['title'] === 'string' ? (row['title'] as string) : id;
          rows.push({ label: id, title: title || id });
        });
      });
      return rows.length ? rows : [{ label: null, title: 'next' }];
    }
    return [{ label: null, title: 'next' }];
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
                const ports = this.outputPortsFor(src);
                const idx = e.label
                  ? Math.max(
                      0,
                      ports.findIndex((p) => p.label === e.label),
                    )
                  : 0;
                return this.outputPortPos(src, idx);
              })();
        if (!from) return null;
        // Midpoint for the edge label — cubic Bézier control points
        // are horizontal so the true midpoint is close to the linear
        // midpoint; good enough for a visual label anchor.
        const midX = (from.x + to.x) / 2;
        const midY = (from.y + to.y) / 2;
        return {
          id: e.id,
          label: e.label ?? null,
          d: this.edgePath(from, to),
          midX,
          midY,
        };
      })
      .filter(
        (
          x,
        ): x is {
          id: string;
          label: string | null;
          d: string;
          midX: number;
          midY: number;
        } => x !== null,
      );
  });

  /** Show a "click a target to connect" hint while a source port is
   *  active. */
  readonly isConnecting = computed(() => this.pendingSourceId() !== null);

  /** Ref to the scroll container so ``fitToScreen`` knows how much
   *  viewport it has to fit the graph into. */
  @ViewChild('canvasViewport', { static: false })
  private canvasViewportRef?: ElementRef<HTMLElement>;

  /** Node ids reachable from the trigger via edge traversal. Nodes
   *  NOT in this set are visually flagged as orphans (dashed border)
   *  so operators notice branches they forgot to wire. Recomputed
   *  every time nodes or edges change (signals-driven). */
  readonly reachableNodeIds = computed(() => {
    const outByNode = new Map<string, string[]>();
    for (const edge of this.edges()) {
      const list = outByNode.get(edge.source);
      if (list) list.push(edge.target);
      else outByNode.set(edge.source, [edge.target]);
    }
    const reached = new Set<string>();
    const stack: string[] = ['trigger'];
    while (stack.length) {
      const cur = stack.pop()!;
      for (const target of outByNode.get(cur) ?? []) {
        if (!reached.has(target)) {
          reached.add(target);
          stack.push(target);
        }
      }
    }
    return reached;
  });

  isOrphan(nodeId: string): boolean {
    return !this.reachableNodeIds().has(nodeId);
  }

  /** True when the node's config is missing any field marked
   *  ``required: true`` in its schema. Read as ``[has red badge in
   *  header]`` — pure UI signal, backend still does the real
   *  validation on Save so no drift risk. */
  nodeHasError(node: CanvasNode): boolean {
    const meta = getNodeType(node.type);
    if (!meta?.configSchema) return false;
    for (const field of meta.configSchema) {
      if (!field.required) continue;
      const parts = field.key.split('.');
      let cur: unknown = node.config;
      for (const p of parts) {
        if (cur === null || cur === undefined || typeof cur !== 'object') {
          cur = undefined;
          break;
        }
        cur = (cur as Record<string, unknown>)[p];
      }
      if (
        cur === null ||
        cur === undefined ||
        cur === '' ||
        (Array.isArray(cur) && cur.length === 0)
      ) {
        return true;
      }
    }
    return false;
  }

  /** Fit the current graph inside the visible canvas viewport by
   *  shrinking zoom just enough. Called from the ``Fit`` button in
   *  the zoom pill. */
  fitToScreen(): void {
    const el = this.canvasViewportRef?.nativeElement;
    if (!el) return;
    this.canvas.fitToScreen(el.clientWidth, el.clientHeight);
  }

  /** Case-insensitive fuzzy match on node type, label, and message
   *  body. Returns up to 8 hits so the dropdown stays scannable on
   *  a 50-node graph. */
  readonly searchResults = computed(() => {
    const q = this.searchQuery().trim().toLowerCase();
    if (q.length < 1) return [];
    const hits: { id: string; label: string; type: string; snippet: string }[] = [];
    for (const n of this.nodes()) {
      const meta = getNodeType(n.type);
      const label = meta?.label ?? n.type;
      const cfg = (n.config as Record<string, unknown>) ?? {};
      const bodyRaw = cfg['body'] ?? cfg['prompt'] ?? cfg['message'] ?? '';
      const body = typeof bodyRaw === 'string' ? bodyRaw : '';
      const haystack = `${label} ${n.type} ${body}`.toLowerCase();
      if (haystack.includes(q)) {
        hits.push({
          id: n.id,
          label,
          type: n.type,
          snippet: body.slice(0, 60),
        });
        if (hits.length >= 8) break;
      }
    }
    return hits;
  });

  /** Scroll the canvas viewport so the given node is centered, then
   *  select it. Used by the search dropdown + minimap click. Position
   *  is the node's absolute canvas coordinate scaled by current zoom. */
  jumpToNode(nodeId: string): void {
    const node = this.nodes().find((n) => n.id === nodeId);
    const el = this.canvasViewportRef?.nativeElement;
    if (!node || !el) return;
    const z = this.zoom();
    const absX = (this.nodeLeftOffset() + node.position.x) * z;
    const absY = node.position.y * z;
    el.scrollTo({
      left: Math.max(0, absX - el.clientWidth / 2 + (this.cardWidth() * z) / 2),
      top: Math.max(0, absY - el.clientHeight / 2 + 100),
      behavior: 'smooth',
    });
    this.canvas.selectedNodeId.set(nodeId);
    this.searchQuery.set('');
  }

  /** Right-click on a node header — capture the screen coordinates
   *  and open the context menu, suppressing the browser default. */
  onNodeContextMenu(nodeId: string, evt: MouseEvent): void {
    evt.preventDefault();
    evt.stopPropagation();
    this.contextMenuNodeId.set(nodeId);
    this.contextMenuPos.set({ x: evt.clientX, y: evt.clientY });
  }

  closeContextMenu(): void {
    this.contextMenuNodeId.set(null);
  }

  /** Clone the node's type + config, drop the copy on the canvas
   *  offset by ~40 px so it doesn't overlap the original. Config is
   *  JSON-cloned via the canvas service's ``updateNodeConfig`` so
   *  nested objects don't share references. */
  duplicateNode(nodeId: string): void {
    const src = this.nodes().find((n) => n.id === nodeId);
    if (!src) {
      this.closeContextMenu();
      return;
    }
    const meta = getNodeType(src.type);
    if (!meta) {
      this.closeContextMenu();
      return;
    }
    const copy = this.canvas.addNode(meta, {
      x: src.position.x + 40,
      y: src.position.y + 40,
    });
    // ``addNode`` seeded the copy with defaultConfig; overlay the
    // source config so the operator gets a real duplicate.
    this.canvas.updateNodeConfig(copy.id, JSON.parse(JSON.stringify(src.config)));
    this.closeContextMenu();
  }

  /** Called from the context menu's Delete row — routes through the
   *  same confirmation modal as clicking the trash icon. */
  requestDeleteFromMenu(nodeId: string): void {
    this.deleteNodeId.set(nodeId);
    this.closeContextMenu();
  }

  openHelp(): void {
    this.helpModalOpen.set(true);
  }

  closeHelp(): void {
    this.helpModalOpen.set(false);
  }

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

  /** Auto-save timer handle. Every 30 s the timer checks ``dirty()``
   *  and fires a save if the operator has pending changes AND no save
   *  is already in flight. Silent — only the normal Save toast fires
   *  on success. Cleared on component destroy via ``destroyRef``. */
  private autoSaveTimer: ReturnType<typeof setInterval> | null = null;
  private readonly AUTO_SAVE_INTERVAL_MS = 30_000;

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id');
      if (id) this.loadBot(id);
    });

    // Kick off the auto-save loop. Interval fires forever; the guard
    // inside skips when there's nothing to save.
    this.autoSaveTimer = setInterval(() => {
      if (this.dirty() && !this.saving() && this.bot() && !this.loading()) {
        this.save();
      }
    }, this.AUTO_SAVE_INTERVAL_MS);

    // Clean up the timer when the component tears down so it doesn't
    // keep firing after the operator navigates away.
    this.destroyRef.onDestroy(() => {
      if (this.autoSaveTimer !== null) {
        clearInterval(this.autoSaveTimer);
        this.autoSaveTimer = null;
      }
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
          this.showToast(`Your bot has been saved (v${updated.version_number}).`);
        },
        error: (err) => {
          // Console-log the raw error so operators (or us) can dig into
          // the underlying cause via devtools. The user-facing message
          // is the extracted API detail so version-conflict / validation
          // messages surface directly.
          console.error('chatbot.save.failed', err);
          this.error.set(extractApiError(err) ?? 'Save failed.');
          this.canvas.saving.set(false);
        },
      });
  }

  /** Guard: publishing (going Live) opens a confirmation dialog first —
   *  once live, the bot starts replying to real customers on real
   *  conversations. Pausing skips the guard (safe direction). */
  toggleLive(): void {
    const bot = this.bot();
    if (!bot) return;
    if (this.dirty()) {
      this.error.set('Save your unsaved changes before toggling Live.');
      return;
    }
    if (!this.isLive()) {
      this.publishConfirmOpen.set(true);
      return;
    }
    this.applyStatusChange(false);
  }

  confirmPublish(): void {
    this.publishConfirmOpen.set(false);
    this.applyStatusChange(true);
  }

  cancelPublish(): void {
    this.publishConfirmOpen.set(false);
  }

  private applyStatusChange(goingLive: boolean): void {
    const bot = this.bot();
    if (!bot) return;
    const call = goingLive ? this.api.publish(bot.id) : this.api.pause(bot.id);
    call.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (updated) => {
        this.canvas.bot.set(updated);
        this.canvas.markSaved(updated.version_number);
        this.showToast(
          goingLive ? 'Your bot is now live and ready to reply.' : 'Your bot has been paused.',
        );
      },
      error: (err) => {
        console.error('chatbot.toggleLive.failed', err);
        this.error.set(extractApiError(err) ?? 'Status change failed.');
      },
    });
  }

  private showToast(message: string): void {
    this.snackBar.open(message, 'OK', {
      duration: 3000,
      horizontalPosition: 'right',
      verticalPosition: 'top',
    });
  }

  /** Prevent tab close / refresh when unsaved changes are pending —
   *  otherwise operators lose 20 minutes of graph editing on an
   *  accidental Ctrl+W. Modern browsers ignore the returned string
   *  and show their own generic warning, but returning any value
   *  triggers the dialog. */
  @HostListener('window:beforeunload', ['$event'])
  onBeforeUnload(event: BeforeUnloadEvent): void {
    if (this.dirty()) {
      event.preventDefault();
      event.returnValue = '';
    }
  }

  openTriggerModal(): void {
    this.triggerModalOpen.set(true);
  }

  openTestModal(): void {
    if (this.dirty()) {
      this.error.set('Save your unsaved changes before running a test.');
      return;
    }
    this.testModalOpen.set(true);
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
    // Swallow the trailing click that follows a drag gesture — the
    // drag itself already moved the node; a click here would either
    // change the selection unexpectedly or complete a pending
    // click-to-connect gesture the user didn't intend.
    if (this.suppressNextClick) {
      this.suppressNextClick = false;
      return;
    }
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

  /** Node-header mousedown starts a drag gesture. We defer any real
   *  move to the document mousemove listener so the drag survives
   *  the cursor leaving the node card. The `moved` flag distinguishes
   *  a click (no drag) from a drag on mouseup so header clicks still
   *  select the node. Pass `'trigger'` as `nodeId` to drag the
   *  trigger card (session-only, not persisted). */
  onNodeHeaderMouseDown(nodeId: string, evt: MouseEvent): void {
    // Left button only — right-click / middle-click shouldn't drag.
    if (evt.button !== 0) return;
    // If a connect gesture is active, defer to click-to-connect
    // rather than dragging.
    if (this.pendingSourceId()) return;
    let startPos: { x: number; y: number };
    if (nodeId === 'trigger') {
      startPos = this.triggerPosition();
    } else {
      const node = this.nodes().find((n) => n.id === nodeId);
      if (!node) return;
      startPos = node.position;
    }
    evt.preventDefault();
    this.dragState = {
      nodeId,
      startMouseX: evt.clientX,
      startMouseY: evt.clientY,
      startPosX: startPos.x,
      startPosY: startPos.y,
      moved: false,
    };
  }

  @HostListener('document:mousemove', ['$event'])
  onDocumentMouseMove(evt: MouseEvent): void {
    // Card resize takes priority over move — the corner grip
    // handler set `cardResizeStart` above.
    if (this.cardResizeStart) {
      const z = this.canvas.zoom() || 1;
      const dx = (evt.clientX - this.cardResizeStart.startX) / z;
      this.canvas.setCardWidth(this.cardResizeStart.startWidth + dx);
      return;
    }
    const drag = this.dragState;
    if (!drag) return;
    // Divide by zoom so a mouse move of N screen pixels translates
    // to N canvas-pixels regardless of the current zoom level —
    // otherwise dragging at 50 % zoom moves the card at half speed.
    const z = this.canvas.zoom() || 1;
    const dx = (evt.clientX - drag.startMouseX) / z;
    const dy = (evt.clientY - drag.startMouseY) / z;
    // Small deadzone — a stray 1-2px jitter shouldn't count as a
    // drag; below the threshold the mouseup handler treats it as a
    // click and selects the node instead.
    if (!drag.moved && Math.abs(dx) < 4 && Math.abs(dy) < 4) return;
    drag.moved = true;
    // Clamp to non-negative — graph coords are anchored at the trigger-
    // column offset so negative x would push cards under the palette.
    const nextX = Math.max(0, drag.startPosX + dx);
    const nextY = Math.max(0, drag.startPosY + dy);
    if (drag.nodeId === 'trigger') {
      this.canvas.triggerPosition.set({ x: nextX, y: nextY });
    } else {
      this.canvas.updateNodePosition(drag.nodeId, { x: nextX, y: nextY });
    }
  }

  @HostListener('document:mouseup', ['$event'])
  onDocumentMouseUp(_evt: MouseEvent): void {
    if (this.cardResizeStart) {
      this.cardResizeStart = null;
      this.suppressNextClick = true;
      setTimeout(() => (this.suppressNextClick = false), 0);
      return;
    }
    const drag = this.dragState;
    if (!drag) return;
    this.dragState = null;
    if (drag.moved) {
      this.suppressNextClick = true;
      // Auto-clear on the next macrotask so a genuine future click
      // isn't accidentally eaten if the browser doesn't emit the
      // trailing click (e.g. drag ended outside the node).
      setTimeout(() => (this.suppressNextClick = false), 0);
    } else if (drag.nodeId !== 'trigger') {
      this.canvas.selectedNodeId.set(drag.nodeId);
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.pendingSourceId()) {
      this.canvas.cancelConnect();
      return;
    }
    if (this.dragState) {
      // Snap back to where we started — cancels an in-progress drag.
      const snapback = { x: this.dragState.startPosX, y: this.dragState.startPosY };
      if (this.dragState.nodeId === 'trigger') {
        this.canvas.triggerPosition.set(snapback);
      } else {
        this.canvas.updateNodePosition(this.dragState.nodeId, snapback);
      }
      this.dragState = null;
    }
  }

  /** Whether a header click should proceed to `selectNode`. During a
   *  drag we bail out on the click at mousedown level (see the
   *  header handler), so this only needs to guard against the tail
   *  end of a drag being counted as a select. */
  isDragging(): boolean {
    return this.dragState !== null && this.dragState.moved;
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

import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  Injector,
  ViewChild,
  afterEveryRender,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { ConfirmDialogComponent } from '../../shared/confirm-dialog/confirm-dialog.component';
import { ConfirmDialogService } from '../../shared/confirm-dialog/confirm-dialog.service';
import { HasUnsavedChanges } from '../../shared/guards/unsaved-changes.guard';
import { ChatbotsApiService, TriggerConfig } from '../chatbots-api.service';
import { CanvasNode, CanvasStateService } from './canvas-state.service';
import { NodeConfigFormComponent } from './node-config-form/node-config-form.component';
import { NodeTypeMeta, getNodeType, humanizeKey } from './node-type-registry';
import { ChatbotHistoryModalComponent } from './history-modal/history-modal.component';
import { ChatbotMinimapComponent } from './minimap/minimap.component';
import { ChatbotStatsModalComponent } from './stats-modal/stats-modal.component';
import { ChatbotPaletteComponent } from './palette/palette.component';
import { ChatbotTestFireModalComponent } from './test-fire-modal/test-fire-modal.component';
import { TriggerConfigModalComponent } from './trigger-modal/trigger-config.modal';
import { VariablesPanelComponent } from './variables-panel/variables-panel.component';
import { BotVariable } from '../../shared/variable-picker/variable-picker-api.service';

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
    ChatbotHistoryModalComponent,
    ChatbotStatsModalComponent,
    VariablesPanelComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './builder.page.html',
})
export class ChatbotBuilderPageComponent implements HasUnsavedChanges {
  private readonly api = inject(ChatbotsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);
  private readonly confirmDialog = inject(ConfirmDialogService);
  private readonly injector = inject(Injector);
  readonly canvas = inject(CanvasStateService);

  readonly loading = signal<boolean>(true);
  /** Why the bot couldn't be loaded (body error state with Retry). */
  readonly loadError = signal<string | null>(null);
  /** Publish / pause request in flight — blocks a double submit. */
  readonly statusChanging = signal<boolean>(false);

  /** Id of the bot being edited (from the route) — Retry reloads it. */
  private botId: string | null = null;
  /** Saving a Live bot updates what customers get immediately; ask once
   *  per page visit before the first manual save of a Live bot. */
  private liveSaveConfirmed = false;
  /** Revision whose auto-save failed — auto-save waits for a new edit
   *  instead of retrying the same failing payload every 30 s. */
  private autoSaveFailedRevision: number | null = null;
  readonly triggerModalOpen = signal<boolean>(false);
  readonly deleteNodeId = signal<string | null>(null);
  readonly testModalOpen = signal<boolean>(false);
  readonly helpModalOpen = signal<boolean>(false);
  readonly publishConfirmOpen = signal<boolean>(false);
  readonly renaming = signal<boolean>(false);
  readonly historyModalOpen = signal<boolean>(false);
  readonly statsModalOpen = signal<boolean>(false);
  readonly variablesPanelOpen = signal<boolean>(false);
  /** Below Tailwind `md` — drives phone-only behaviour (drawer panels,
   *  closing the palette after adding a step). */
  readonly isPhone = signal<boolean>(window.matchMedia('(max-width: 767.98px)').matches);
  /** Display text for raw keys like the bot status. */
  protected readonly humanize = humanizeKey;

  @ViewChild('renameInput') private renameInputRef?: ElementRef<HTMLInputElement>;

  /** Session variables — every `save_to` in the current graph that
   *  writes to `answers.<key>` becomes a session variable operators
   *  can reference from downstream nodes. Contact / lead / custom
   *  save_targets aren't session vars — they're already listed under
   *  the Contact / Lead groups the API endpoint returns. */
  readonly sessionVariables = computed<BotVariable[]>(() => {
    const seen = new Set<string>();
    const out: BotVariable[] = [];
    for (const node of this.canvas.nodes()) {
      const cfg = (node.config ?? {}) as Record<string, unknown>;
      const candidates = [cfg['save_to'], cfg['save_reply_to']];
      for (const raw of candidates) {
        if (typeof raw !== 'string') continue;
        const path = raw.trim();
        if (!path.startsWith('answers.') || seen.has(path)) continue;
        seen.add(path);
        out.push({
          path,
          label: path.slice('answers.'.length) || path,
          description: `Answer captured earlier in this bot (from the "${getNodeType(node.type)?.label ?? humanizeKey(node.type)}" step).`,
        });
      }
    }
    return out;
  });

  /** Right-click node menu — the id of the node whose context menu
   *  is open, plus screen coordinates where the operator clicked. */
  readonly contextMenuNodeId = signal<string | null>(null);
  readonly contextMenuPos = signal<{ x: number; y: number }>({ x: 0, y: 0 });

  /** Node search box (visible pill at top of canvas). Empty string
   *  hides the dropdown. */
  readonly searchQuery = signal<string>('');
  /** Results dropdown visibility — closes on canvas click / Esc while
   *  keeping the typed query. */
  readonly searchOpen = signal<boolean>(false);

  /** Drafts for the raw-JSON fallback editor (unknown node types),
   *  keyed by node id — keeps the cursor still and the parse error
   *  visible while typing. */
  readonly fallbackJsonDrafts = signal<Record<string, string>>({});

  /** Each connection dot's centre RELATIVE TO ITS CARD (unscaled px),
   *  measured from the DOM after render. Wires add this to the card's
   *  live position, so they hit the real dots — including while a card
   *  is dragged — instead of fixed guesses. Keys: `out:<node>::<label>`,
   *  `in:<node>`; the trigger card is node `trigger`. */
  private readonly portOffsets = signal<Record<string, { x: number; y: number }>>({});
  private cardObserver: ResizeObserver | null = null;
  private readonly observedCards = new WeakSet<Element>();

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

  /** Fallback trigger port (before the dot has been measured). The
   *  card's `left/top` are `triggerPosition` itself. */
  triggerPortPos(): { x: number; y: number } {
    const pos = this.triggerPosition();
    return {
      x: pos.x + this.cardWidth(),
      y: pos.y + this.TRIGGER_HEIGHT / 2,
    };
  }

  /** Card top-left in canvas coords — the base the measured port
   *  offsets are relative to. */
  private cardOrigin(nodeId: string, node?: CanvasNode): { x: number; y: number } {
    if (nodeId === 'trigger') return this.triggerPosition();
    return { x: this.nodeLeftOffset() + (node?.position.x ?? 0), y: node?.position.y ?? 0 };
  }

  private portAt(
    key: string,
    origin: { x: number; y: number },
    fallback: { x: number; y: number },
  ): { x: number; y: number } {
    const o = this.portOffsets()[key];
    return o ? { x: origin.x + o.x, y: origin.y + o.y } : fallback;
  }

  /** Measure every `[data-port]` dot relative to its card, plus each
   *  node card's height (for the palette's drop position). Runs after
   *  every render and when a card resizes; only writes signals when
   *  something actually moved, so it can't loop. */
  private measurePorts(): void {
    const content = this.canvasContentRef?.nativeElement;
    if (!content) return;
    const z = this.zoom() || 1;
    const offsets: Record<string, { x: number; y: number }> = {};
    content.querySelectorAll<HTMLElement>('[data-port]').forEach((dot) => {
      const card = dot.closest<HTMLElement>('[data-cb-card]');
      const key = dot.dataset['port'];
      if (!card || !key) return;
      const c = card.getBoundingClientRect();
      const r = dot.getBoundingClientRect();
      offsets[key] = {
        x: Math.round((r.left + r.width / 2 - c.left) / z),
        y: Math.round((r.top + r.height / 2 - c.top) / z),
      };
    });
    const heights: Record<string, number> = {};
    content.querySelectorAll<HTMLElement>('[data-node-id]').forEach((card) => {
      const id = card.dataset['nodeId'];
      if (id) heights[id] = card.offsetHeight;
      if (!this.observedCards.has(card)) {
        this.observedCards.add(card);
        this.cardObserver?.observe(card);
      }
    });
    if (JSON.stringify(offsets) !== JSON.stringify(this.portOffsets())) {
      this.portOffsets.set(offsets);
    }
    if (JSON.stringify(heights) !== JSON.stringify(this.canvas.cardHeights())) {
      this.canvas.cardHeights.set(heights);
    }
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
      return (meta.labels ?? []).map((l) => ({ label: l, title: humanizeKey(l) }));
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
        const to = this.portAt(
          `in:${target.id}`,
          this.cardOrigin(target.id, target),
          this.inputPortPos(target),
        );
        let title: string | null = null;
        let from: { x: number; y: number } | null = null;
        if (e.source === 'trigger') {
          from = this.portAt('out:trigger::', this.cardOrigin('trigger'), this.triggerPortPos());
        } else {
          const src = nodesById.get(e.source);
          if (!src) return null;
          const ports = this.outputPortsFor(src);
          const idx = e.label
            ? Math.max(
                0,
                ports.findIndex((p) => p.label === e.label),
              )
            : 0;
          // Show what the customer sees (button title / port name),
          // not the stored id.
          title = e.label ? (ports.find((p) => p.label === e.label)?.title ?? e.label) : null;
          from = this.portAt(
            `out:${src.id}::${e.label ?? ''}`,
            this.cardOrigin(src.id, src),
            this.outputPortPos(src, idx),
          );
        }
        // Midpoint for the edge label — cubic Bézier control points
        // are horizontal so the true midpoint is close to the linear
        // midpoint; good enough for a visual label anchor.
        const midX = (from.x + to.x) / 2;
        const midY = (from.y + to.y) / 2;
        return {
          id: e.id,
          label: title,
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

  /** The scaled content layer holding the cards — measured by
   *  ``fitToScreen``. */
  @ViewChild('canvasContent', { static: false })
  private canvasContentRef?: ElementRef<HTMLElement>;

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

  /** Steps the trigger can never reach — called out before going Live. */
  readonly unreachableCount = computed(
    () => this.nodes().filter((n) => !this.reachableNodeIds().has(n.id)).length,
  );

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

  /** Fit the whole graph inside the visible canvas viewport by
   *  shrinking zoom just enough, then scroll back to the origin so the
   *  flow is seen at once. Called from the ``Fit`` button in the zoom
   *  pill and automatically after every load. The bounding box comes
   *  from the rendered cards (`[data-cb-card]`) — `offsetLeft/Top/
   *  Width/Height` are layout values, unaffected by the CSS `scale`,
   *  so they measure real card heights instead of estimating them. */
  fitToScreen(): void {
    const el = this.canvasViewportRef?.nativeElement;
    const content = this.canvasContentRef?.nativeElement;
    if (!el || !content) return;
    let right = 0;
    let bottom = 0;
    content.querySelectorAll<HTMLElement>('[data-cb-card]').forEach((card) => {
      right = Math.max(right, card.offsetLeft + card.offsetWidth);
      bottom = Math.max(bottom, card.offsetTop + card.offsetHeight);
    });
    this.canvas.fitToScreen(
      el.clientWidth,
      el.clientHeight,
      right + this.CANVAS_PAD * 2,
      bottom + this.CANVAS_PAD * 2,
    );
    el.scrollTo({ left: 0, top: 0 });
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
    // Keep the menu (~170 × 90 px) on screen near the right / bottom edge.
    this.contextMenuPos.set({
      x: Math.max(4, Math.min(evt.clientX, window.innerWidth - 176)),
      y: Math.max(4, Math.min(evt.clientY, window.innerHeight - 96)),
    });
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

  openHistory(): void {
    if (!this.bot()) return;
    this.historyModalOpen.set(true);
  }

  closeHistory(): void {
    this.historyModalOpen.set(false);
  }

  /** Called after a version restore — reload the bot so the canvas
   *  reflects the restored graph. */
  onHistoryRestored(): void {
    const bot = this.bot();
    if (!bot) return;
    this.showToast('Version restored.');
    // Same bot — keep the operator's zoom / palette / card width.
    this.loadBot(bot.id, { keepView: true });
  }

  openStats(): void {
    if (!this.bot()) return;
    this.statsModalOpen.set(true);
  }

  closeStats(): void {
    this.statsModalOpen.set(false);
  }

  startRename(): void {
    if (!this.bot()) return;
    this.renaming.set(true);
    // `autofocus` doesn't apply to inputs inserted after page load.
    afterNextRender(
      () => {
        const el = this.renameInputRef?.nativeElement;
        el?.focus();
        el?.select();
      },
      { injector: this.injector },
    );
  }

  cancelRename(): void {
    this.renaming.set(false);
  }

  /** PATCH just the ``name`` field on the bot. Rejects empty / unchanged
   *  values silently. Uses the same optimistic-lock cursor the graph
   *  save uses so a concurrent editor's save doesn't get overwritten. */
  commitRename(nextRaw: string): void {
    if (!this.renaming()) return;
    const bot = this.bot();
    if (!bot) {
      this.renaming.set(false);
      return;
    }
    const next = (nextRaw ?? '').trim();
    if (!next || next === bot.name) {
      this.renaming.set(false);
      return;
    }
    this.renaming.set(false);
    // Show the new name straight away; put the old one back on failure.
    const previousName = bot.name;
    this.canvas.bot.set({ ...bot, name: next });
    this.api
      .update(bot.id, {
        expected_version: this.canvas.expectedVersion(),
        name: next,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.canvas.acceptServerBot(updated);
          this.showToast(`Renamed to "${updated.name}".`);
        },
        error: (err) => {
          console.error('chatbot.rename.failed', err);
          const current = this.bot();
          if (current) this.canvas.bot.set({ ...current, name: previousName });
          this.toast.error('Rename failed', { subtitle: extractApiError(err) ?? undefined });
        },
      });
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
   *  and saves silently when there are pending changes, no save is in
   *  flight, and the bot is NOT Live — a Live bot's save goes straight
   *  to customers, so it only saves when the operator clicks Save.
   *  Cleared on component destroy via ``destroyRef``. */
  private autoSaveTimer: ReturnType<typeof setInterval> | null = null;
  private readonly AUTO_SAVE_INTERVAL_MS = 30_000;

  /** Phone breakpoint (< Tailwind `md`). Drives the opening zoom /
   *  palette / minimap defaults via ``applyViewportDefaults``. */
  private readonly phoneQuery = window.matchMedia('(max-width: 767.98px)');

  constructor() {
    // Re-apply the screen-class defaults when the viewport crosses the
    // phone breakpoint so a rotate / resize never leaves a desktop 100 %
    // zoom on a phone (or 25 % on a desktop).
    const onPhoneChange = (e: MediaQueryListEvent): void => {
      this.isPhone.set(e.matches);
      this.canvas.applyViewportDefaults(e.matches);
    };
    this.phoneQuery.addEventListener('change', onPhoneChange);
    this.destroyRef.onDestroy(() => this.phoneQuery.removeEventListener('change', onPhoneChange));

    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id');
      if (id) this.loadBot(id);
    });

    // The canvas store is app-wide: clear it on the way out so the next
    // bot never starts with this one's graph, name or "Saving…" state.
    this.destroyRef.onDestroy(() => this.canvas.reset());

    // Wire geometry: measure the real dot positions after each render
    // and whenever a card's size changes (typing, resize-y, width grip).
    this.cardObserver = new ResizeObserver(() => this.measurePorts());
    this.destroyRef.onDestroy(() => this.cardObserver?.disconnect());
    afterEveryRender(() => this.measurePorts());

    // Keep the floating zoom pill + minimap clear of the docked
    // Variables panel on desktop (on phones the panel is a drawer).
    effect(() => {
      this.canvas.rightOverlayOffset.set(this.variablesPanelOpen() && !this.isPhone() ? 344 : null);
    });

    // Kick off the auto-save loop. Interval fires forever; the guard
    // inside skips when there's nothing to save.
    this.autoSaveTimer = setInterval(() => {
      if (
        this.dirty() &&
        !this.saving() &&
        this.bot() &&
        !this.loading() &&
        !this.isLive() &&
        this.autoSaveFailedRevision !== this.canvas.revision
      ) {
        void this.save({ auto: true });
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

  /** `keepView` (history restore of the same bot) keeps zoom, palette
   *  and card width instead of resetting to screen defaults. */
  private loadBot(id: string, opts: { keepView?: boolean } = {}): void {
    this.botId = id;
    // Never show (or save into) the previously opened bot while this
    // one loads — or if it fails to load.
    if (!opts.keepView) this.canvas.reset();
    this.liveSaveConfirmed = false;
    this.autoSaveFailedRevision = null;
    this.fallbackJsonDrafts.set({});
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .get(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (bot) => {
          this.canvas.loadFrom(bot);
          this.loading.set(false);
          if (opts.keepView) return;
          // Opening zoom / palette / minimap for this screen class; on
          // desktop also fit a large graph on screen once it's rendered
          // (fitToScreen never zooms in past 100 %).
          this.canvas.applyViewportDefaults(this.phoneQuery.matches);
          if (!this.phoneQuery.matches) {
            afterNextRender(() => this.fitToScreen(), { injector: this.injector });
          }
        },
        error: (err) => {
          this.loadError.set(extractApiError(err) ?? 'Could not load this bot.');
          this.loading.set(false);
        },
      });
  }

  retryLoad(): void {
    if (this.botId) this.loadBot(this.botId);
  }

  /** Unsaved-changes guard (in-app navigation) — tab close is covered
   *  by `onBeforeUnload`. */
  hasUnsavedChanges(): boolean {
    return this.dirty();
  }

  /** Save the graph. Manual saves of a Live bot confirm first (the change
   *  reaches customers immediately); auto-saves are silent and never
   *  run on Live bots. */
  async save(opts: { auto?: boolean } = {}): Promise<void> {
    const bot = this.bot();
    if (!bot || this.saving()) return;
    if (!opts.auto && this.isLive() && !this.liveSaveConfirmed) {
      const ok = await this.confirmDialog.ask({
        title: 'Save changes to a Live bot?',
        body: 'This bot is replying to customers right now — saving updates it for every new conversation immediately. To edit safely, Pause it first.',
        confirmLabel: 'Save to Live bot',
      });
      if (!ok) return;
      this.liveSaveConfirmed = true;
    }
    this.canvas.saving.set(true);
    const revision = this.canvas.revision;
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
          this.canvas.markSaved(updated.version_number, revision);
          this.autoSaveFailedRevision = null;
          if (!opts.auto) {
            this.showToast(`Your bot has been saved (v${updated.version_number}).`);
          }
        },
        error: (err) => {
          // Console-log the raw error so operators (or us) can dig into
          // the underlying cause via devtools. The user-facing message
          // is the extracted API detail so version-conflict / validation
          // messages surface directly.
          console.error('chatbot.save.failed', err);
          this.canvas.saving.set(false);
          if (opts.auto) this.autoSaveFailedRevision = revision;
          if (err instanceof HttpErrorResponse && err.status === 409) {
            void this.onSaveConflict();
            return;
          }
          this.toast.error(opts.auto ? 'Auto-save failed' : 'Save failed', {
            subtitle:
              (extractApiError(err) ?? 'Please try again.') +
              (opts.auto ? ' Auto-save resumes after your next edit.' : ''),
          });
        },
      });
  }

  /** Someone (another tab / teammate) saved a newer version — the
   *  optimistic lock refused ours. Offer to reload the latest. */
  private async onSaveConflict(): Promise<void> {
    const ok = await this.confirmDialog.ask({
      title: 'This bot was changed somewhere else',
      body: 'A newer version was saved in another tab or by a teammate, so your save was blocked. Reload the latest version? Your unsaved changes here will be lost.',
      confirmLabel: 'Reload latest',
      danger: true,
    });
    if (ok && this.botId) this.loadBot(this.botId, { keepView: true });
  }

  /** Guard: publishing (going Live) opens a confirmation dialog first —
   *  once live, the bot starts replying to real customers on real
   *  conversations. Pausing skips the guard (safe direction). */
  toggleLive(): void {
    const bot = this.bot();
    if (!bot) return;
    if (this.dirty()) {
      this.toast.warn('Save your changes first', {
        subtitle: 'Going Live / pausing applies to the saved version.',
      });
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
    if (!bot || this.statusChanging()) return;
    this.statusChanging.set(true);
    const call = goingLive ? this.api.publish(bot.id) : this.api.pause(bot.id);
    call.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (updated) => {
        this.statusChanging.set(false);
        this.canvas.acceptServerBot(updated);
        this.liveSaveConfirmed = false;
        this.showToast(
          goingLive ? 'Your bot is now live and ready to reply.' : 'Your bot has been paused.',
        );
      },
      error: (err) => {
        this.statusChanging.set(false);
        console.error('chatbot.toggleLive.failed', err);
        this.toast.error(goingLive ? 'Could not make the bot Live' : 'Could not pause the bot', {
          subtitle: extractApiError(err) ?? undefined,
        });
      },
    });
  }

  /** Thin wrapper preserved so the four existing call sites don't
   *  each need to pick a variant — every current caller is a
   *  positive confirmation (version restored / renamed / saved /
   *  live). If a new caller needs a warn/error variant, hit
   *  `this.toast.error(...)` directly. */
  private showToast(message: string): void {
    this.toast.success(message);
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

  /** Trigger card click — ignored when it is the tail of a drag or a
   *  card resize, so moving / resizing doesn't pop the settings modal. */
  onTriggerCardClick(evt: MouseEvent): void {
    evt.stopPropagation();
    if (this.suppressNextClick) {
      this.suppressNextClick = false;
      return;
    }
    this.openTriggerModal();
  }

  openTestModal(): void {
    if (this.dirty()) {
      this.toast.warn('Save your changes first', {
        subtitle: 'Tests run the saved version of the bot.',
      });
      return;
    }
    this.testModalOpen.set(true);
  }

  onTriggerSave(cfg: TriggerConfig): void {
    this.canvas.setTriggerConfig(cfg);
    this.triggerModalOpen.set(false);
  }

  /** The palette has just added (and selected) a node: on phones close
   *  the drawer so the canvas is visible, then scroll the new node into
   *  view on every screen size. */
  onPaletteAdd(_meta: NodeTypeMeta): void {
    if (this.isPhone()) this.canvas.paletteCollapsed.set(true);
    const id = this.selectedNodeId();
    if (!id) return;
    afterNextRender(() => this.jumpToNode(id), { injector: this.injector });
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

  onOutputPortClick(sourceId: string, label: string | null, evt: Event): void {
    evt.stopPropagation();
    if (this.pendingSourceId() === sourceId && this.canvas.pendingSourceLabel() === label) {
      this.canvas.cancelConnect();
      return;
    }
    this.canvas.beginConnect(sourceId, label);
  }

  onInputPortClick(targetId: string, evt: Event): void {
    evt.stopPropagation();
    if (!this.pendingSourceId()) return;
    this.canvas.completeConnect(targetId);
  }

  /** Click on empty canvas — clears any pending connect gesture and
   *  deselects the current node. */
  onCanvasClick(): void {
    this.searchOpen.set(false);
    if (this.pendingSourceId()) {
      this.canvas.cancelConnect();
      return;
    }
    this.canvas.selectedNodeId.set(null);
  }

  /** Builder shortcuts: Ctrl/⌘+S saves; Delete / Backspace removes the
   *  selected step (with the usual confirm) unless you're typing or a
   *  dialog is open. */
  @HostListener('document:keydown', ['$event'])
  onKeydown(evt: KeyboardEvent): void {
    if ((evt.ctrlKey || evt.metaKey) && evt.key.toLowerCase() === 's') {
      evt.preventDefault();
      if (this.dirty() && !this.saving()) void this.save();
      return;
    }
    if (evt.key !== 'Delete' && evt.key !== 'Backspace') return;
    const target = evt.target as HTMLElement | null;
    if (target?.closest('input, textarea, select, [contenteditable="true"]')) return;
    const selected = this.selectedNodeId();
    if (!selected || this.anyDialogOpen()) return;
    evt.preventDefault();
    this.deleteNodeId.set(selected);
  }

  private anyDialogOpen(): boolean {
    return (
      this.triggerModalOpen() ||
      this.testModalOpen() ||
      this.helpModalOpen() ||
      this.historyModalOpen() ||
      this.statsModalOpen() ||
      this.publishConfirmOpen() ||
      this.deleteNodeId() !== null ||
      this.contextMenuNodeId() !== null
    );
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

  // Pointer events (not mouse events) so dragging cards, the trigger
  // and resize grips also works with touch and pens.
  @HostListener('document:pointermove', ['$event'])
  onDocumentMouseMove(evt: PointerEvent): void {
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

  @HostListener('document:pointerup')
  @HostListener('document:pointercancel')
  onDocumentMouseUp(): void {
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
    if (this.contextMenuNodeId()) {
      this.closeContextMenu();
      return;
    }
    if (this.helpModalOpen()) {
      this.closeHelp();
      return;
    }
    if (this.searchOpen()) {
      this.searchOpen.set(false);
      return;
    }
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

  fallbackJsonText(node: CanvasNode): string {
    return this.fallbackJsonDrafts()[node.id] ?? JSON.stringify(node.config, null, 2);
  }

  /** Parse error for the fallback editor's current draft, if any. */
  fallbackJsonError(nodeId: string): string | null {
    const raw = this.fallbackJsonDrafts()[nodeId];
    if (raw === undefined) return null;
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? null
        : 'Config must be a JSON object ({ … }).';
    } catch (e) {
      return e instanceof Error ? e.message : 'Invalid JSON';
    }
  }

  updateNodeConfigJson(nodeId: string, raw: string): void {
    this.fallbackJsonDrafts.update((d) => ({ ...d, [nodeId]: raw }));
    if (this.fallbackJsonError(nodeId)) return;
    this.canvas.updateNodeConfig(nodeId, JSON.parse(raw) as Record<string, unknown>);
  }

  /** On blur, drop a valid draft so the editor shows the formatted value. */
  onFallbackJsonBlur(nodeId: string): void {
    if (this.fallbackJsonError(nodeId)) return;
    this.fallbackJsonDrafts.update((d) => {
      const next = { ...d };
      delete next[nodeId];
      return next;
    });
  }

  /** Display name for the trigger's channel. */
  channelLabel(channel: string | null | undefined): string {
    if (channel === 'whatsapp') return 'WhatsApp';
    if (channel === 'email') return 'Email';
    return 'Any channel';
  }
}

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

import { ChatbotsApiService, TriggerConfig } from '../chatbots-api.service';
import { CanvasStateService } from './canvas-state.service';
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

  readonly bot = this.canvas.bot;
  readonly nodes = this.canvas.nodes;
  readonly triggerConfig = this.canvas.triggerConfig;
  readonly selectedNodeId = this.canvas.selectedNodeId;
  readonly dirty = this.canvas.dirty;
  readonly saving = this.canvas.saving;

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
    this.canvas.selectedNodeId.set(nodeId);
  }

  deleteNode(nodeId: string, evt: MouseEvent): void {
    evt.stopPropagation();
    if (!window.confirm('Delete this node? Its outbound edges will be removed too.')) return;
    this.canvas.deleteNode(nodeId);
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

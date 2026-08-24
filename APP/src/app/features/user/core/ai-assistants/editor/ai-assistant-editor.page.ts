/**
 * AI Assistant editor page (``tasks/ai-assistants`` Step 7).
 *
 * Two-pane layout mirroring Pabbly Chatflow's editor:
 *
 *   * Header bar — back arrow, inline-editable assistant name,
 *     status pill, Embed button (disabled until Step 15 lands the
 *     public router), Save AI Assistant button.
 *   * Left pane (60% width) — tab strip (4 tabs) + the currently
 *     mounted tab component. Steps 8/11/12/13 fill the tab bodies;
 *     this step ships placeholders.
 *   * Right pane (40% width) — the live-preview component that
 *     subscribes to the shared form-state signal store and
 *     re-renders locally on every change with zero network calls.
 *
 * :class:`AssistantFormStateService` is provided at the component
 * level so a new instance mounts on every navigation to a fresh
 * assistant — no stale state bleeds between editors.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { toObservable } from '@angular/core/rxjs-interop';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { LucideAngularModule } from 'lucide-angular';
import { switchMap } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';
import { AiAssistantsApiService } from '../ai-assistants-api.service';
import { AssistantFormStateService } from '../form-state.service';
import { EmbedSnippetModalComponent } from './embed/embed-snippet-modal.component';
import { AssistantPreviewComponent } from './preview/assistant-preview.component';
import { AssistantInterfaceTabComponent } from './tabs/assistant-interface-tab.component';
import { InstructionsTabComponent } from './tabs/instructions-tab.component';
import { KnowledgeSourceTabComponent } from './tabs/knowledge-source-tab.component';
import { StylingTabComponent } from './tabs/styling-tab.component';

type TabId = 'instructions' | 'knowledge' | 'interface' | 'styling';

// User-visible channel labels, keyed on the AiAssistantChannel enum
// values. Used by the channel-conflict 409 toast in ``save()`` so the
// message reads "WhatsApp is already handled by …" instead of the raw
// enum string. Falls back to the raw key for unknown channels (safe
// against future channels shipping frontend-first).
function _channelLabel(key: string): string {
  switch (key) {
    case 'ai_widget':
      return 'Website widget';
    case 'whatsapp':
      return 'WhatsApp';
    case 'email':
      return 'Email';
    default:
      return key;
  }
}

interface TabDescriptor {
  id: TabId;
  label: string;
}

const TABS: TabDescriptor[] = [
  { id: 'instructions', label: 'AI Instructions' },
  { id: 'knowledge', label: 'Knowledge Source' },
  { id: 'interface', label: 'Assistant Interface' },
  { id: 'styling', label: 'Styling' },
];

@Component({
  selector: 'app-ai-assistant-editor-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [AssistantFormStateService],
  imports: [
    FormsModule,
    LucideAngularModule,
    AssistantPreviewComponent,
    EmbedSnippetModalComponent,
    InstructionsTabComponent,
    KnowledgeSourceTabComponent,
    AssistantInterfaceTabComponent,
    StylingTabComponent,
  ],
  templateUrl: './ai-assistant-editor.page.html',
})
export class AiAssistantEditorPage {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(AiAssistantsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);
  protected readonly formState = inject(AssistantFormStateService);

  protected readonly tabs = TABS;
  protected readonly activeTab = signal<TabId>('instructions');
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saving = signal(false);
  protected readonly saveError = signal<string | null>(null);
  protected readonly savedAt = signal<number | null>(null);
  protected readonly publishing = signal(false);
  protected readonly nameEditing = signal(false);
  protected readonly nameDraft = signal('');
  /** Step 15 — controls the visibility of the embed snippet modal.
   *  Opened from the header's Embed button; the modal handles its
   *  own load / issue / rotate / revoke lifecycle. */
  protected readonly embedModalOpen = signal(false);

  protected openEmbedModal(): void {
    if (this.formState.assistantId()) {
      this.embedModalOpen.set(true);
    }
  }

  protected closeEmbedModal(): void {
    this.embedModalOpen.set(false);
  }

  protected readonly canSave = computed(
    () => this.formState.loaded() && this.formState.dirty() && !this.saving(),
  );

  // Publish requires: assistant loaded, no unsaved changes (publishing
  // pushes the DB row live — pending edits would silently ship or, worse,
  // never ship), and not currently mid-flight. Kept as its own computed
  // so the button tooltip can explain WHICH gate is blocking.
  protected readonly canPublish = computed(
    () =>
      this.formState.loaded() && !this.formState.dirty() && !this.publishing() && !this.saving(),
  );

  protected readonly publishBlockedReason = computed<string | null>(() => {
    if (!this.formState.loaded()) return 'Loading…';
    if (this.formState.dirty()) return 'Save your changes before publishing.';
    if (this.publishing() || this.saving()) return null;
    return 'Publish this assistant so the embed widget can serve it.';
  });

  protected readonly embedBlockedReason = computed<string | null>(() => {
    if (!this.formState.assistantId()) return 'Save assistant first';
    if (this.formState.status() !== 'active') {
      return 'Publish the assistant first — the embed widget only serves active assistants.';
    }
    return 'Get the install snippet';
  });

  constructor() {
    // Load whenever the :id in the route changes (covers back/forward
    // navigation between assistants without a full page refresh).
    toObservable(this.activeTab); // touch to register in DI graph
    this.route.paramMap
      .pipe(
        switchMap((params) => {
          const id = params.get('id');
          this.loading.set(true);
          this.loadError.set(null);
          this.formState.reset();
          if (!id) {
            this.loadError.set('Missing assistant id.');
            this.loading.set(false);
            return [];
          }
          return this.api.get(id);
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (row) => {
          this.formState.load(row);
          this.nameDraft.set(row.name);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load assistant.');
        },
      });
  }

  protected setActiveTab(id: TabId): void {
    this.activeTab.set(id);
  }

  protected back(): void {
    void this.router.navigate(['/user/ai-assistants']);
  }

  protected beginNameEdit(): void {
    this.nameDraft.set(this.formState.formState().name);
    this.nameEditing.set(true);
  }

  protected onNameInput(event: Event): void {
    this.nameDraft.set((event.target as HTMLInputElement).value);
  }

  protected commitNameEdit(): void {
    const next = this.nameDraft().trim();
    if (next && next !== this.formState.formState().name) {
      this.formState.patch({ name: next });
    }
    this.nameEditing.set(false);
  }

  protected cancelNameEdit(): void {
    this.nameEditing.set(false);
  }

  protected onNameKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter') {
      event.preventDefault();
      this.commitNameEdit();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      this.cancelNameEdit();
    }
  }

  protected save(): void {
    if (!this.canSave()) return;
    const id = this.formState.assistantId();
    if (!id) return;
    this.saving.set(true);
    this.saveError.set(null);
    const payload = this.formState.buildUpdatePayload();
    this.api
      .update(id, payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.saving.set(false);
          this.formState.applySaveResponse(row);
          this.savedAt.set(Date.now());
          this.toast.success('Assistant saved.');
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          const message = this._friendlyErrorMessage(err);
          this.saveError.set(message);
          this.toast.error(message);
        },
      });
  }

  // Translate structured backend errors into copy an operator can act
  // on. The omnichannel Step 2 channel-conflict 409 carries the other
  // assistant's name in its detail body — surface it inline rather than
  // showing a generic "Save failed."
  //
  // The API's custom HTTPException handler (main.py) flattens a dict
  // ``detail`` into the response body itself — so a 409 arrives as
  // ``{reason, channel, ...}`` on ``err.error`` directly, not nested
  // under ``.detail``. Check both shapes so a future revert to the
  // FastAPI-standard envelope wouldn't silently regress this path.
  private _friendlyErrorMessage(err: HttpErrorResponse): string {
    const body = err.error;
    const structured =
      body && typeof body === 'object'
        ? (body as { detail?: unknown; reason?: unknown }).detail &&
          typeof (body as { detail?: unknown }).detail === 'object'
          ? (body as { detail: Record<string, unknown> }).detail
          : (body as Record<string, unknown>)
        : null;
    if (
      err.status === 409 &&
      structured &&
      typeof structured === 'object' &&
      (structured as { reason?: unknown }).reason === 'channel_already_bound'
    ) {
      const s = structured as {
        channel?: unknown;
        other_assistant_name?: unknown;
      };
      const ch = typeof s.channel === 'string' ? s.channel : 'that channel';
      const chLabel = _channelLabel(ch);
      const other =
        typeof s.other_assistant_name === 'string' ? s.other_assistant_name : 'another assistant';
      return `${chLabel} is already handled by '${other}'. Unbind it there first.`;
    }
    return extractApiError(err) ?? 'Save failed.';
  }

  protected publish(): void {
    if (!this.canPublish()) return;
    const id = this.formState.assistantId();
    if (!id) return;
    this.publishing.set(true);
    this.api
      .activate(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.publishing.set(false);
          this.formState.load(row);
          this.toast.success('Assistant published', {
            subtitle: 'Embed widget is live.',
          });
        },
        error: (err: HttpErrorResponse) => {
          this.publishing.set(false);
          this.toast.error(extractApiError(err) ?? 'Publish failed.');
        },
      });
  }
}

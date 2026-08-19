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
  protected readonly formState = inject(AssistantFormStateService);

  protected readonly tabs = TABS;
  protected readonly activeTab = signal<TabId>('instructions');
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saving = signal(false);
  protected readonly saveError = signal<string | null>(null);
  protected readonly savedAt = signal<number | null>(null);
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
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.saveError.set(extractApiError(err) ?? 'Save failed.');
        },
      });
  }
}

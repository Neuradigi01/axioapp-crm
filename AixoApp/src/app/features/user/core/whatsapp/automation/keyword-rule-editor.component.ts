import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  ConversationTag,
  ConversationsApiService,
} from '../../conversations/conversations-api.service';
import { StaffApiService, StaffListItem } from '../../staff/staff-api.service';
import {
  WhatsAppTemplateRead,
  WhatsAppTemplatesApiService,
} from '../templates/whatsapp-templates-api.service';

import {
  KeywordActionPayload,
  KeywordActionType,
  KeywordMatchType,
  KeywordRule,
  KeywordRuleUpsert,
  WhatsAppAutomationApiService,
} from './whatsapp-automation-api.service';

type ActionDraft = {
  action_type: KeywordActionType;
  action_config: Record<string, unknown>;
};

/**
 * Keyword rule editor (whatsapp-platform-upgrade Step 17).
 *
 * Inline panel for one rule — name, keywords, match type, action
 * stack. Submits the whole rule on Save (the backend swaps actions
 * in place). Used in both Create and Edit flows.
 */
@Component({
  selector: 'app-keyword-rule-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  templateUrl: './keyword-rule-editor.component.html',
})
export class KeywordRuleEditorComponent {
  private readonly api = inject(WhatsAppAutomationApiService);
  private readonly templatesApi = inject(WhatsAppTemplatesApiService);
  private readonly staffApi = inject(StaffApiService);
  private readonly conversationsApi = inject(ConversationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input() set rule(value: KeywordRule | null) {
    if (value) {
      this.editingId.set(value.id);
      this.name.set(value.name);
      this.keywordsInput.set(value.keywords.join(', '));
      this.matchType.set(value.match_type);
      this.enabled.set(value.enabled);
      this.priority.set(value.priority);
      this.actions.set(
        value.actions.map((a) => ({
          action_type: a.action_type,
          action_config: { ...a.action_config },
        })),
      );
    } else {
      this.editingId.set(null);
      this.name.set('');
      this.keywordsInput.set('');
      this.matchType.set('contains');
      this.enabled.set(true);
      this.priority.set(100);
      this.actions.set([]);
    }
  }

  @Output() readonly saved = new EventEmitter<KeywordRule>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly editingId = signal<string | null>(null);

  protected readonly name = signal<string>('');
  protected readonly keywordsInput = signal<string>('');
  protected readonly matchType = signal<KeywordMatchType>('contains');
  protected readonly enabled = signal<boolean>(true);
  protected readonly priority = signal<number>(100);
  protected readonly actions = signal<ActionDraft[]>([]);

  protected readonly saving = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);

  protected readonly templates = signal<WhatsAppTemplateRead[]>([]);
  protected readonly staff = signal<StaffListItem[]>([]);
  protected readonly tags = signal<ConversationTag[]>([]);

  protected readonly approvedTemplates = computed(() =>
    this.templates().filter((t) => t.submission_status === 'approved'),
  );

  protected readonly keywords = computed(() =>
    this.keywordsInput()
      .split(',')
      .map((k) => k.trim())
      .filter((k) => k.length > 0),
  );

  constructor() {
    this.templatesApi
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.templates.set(rows),
        error: () => this.templates.set([]),
      });
    this.staffApi
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.staff.set(rows),
        error: () => this.staff.set([]),
      });
    this.conversationsApi
      .listTags()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.tags.set(rows),
        error: () => this.tags.set([]),
      });
  }

  // --- actions stack ----------------------------------------------

  protected addAction(action_type: KeywordActionType): void {
    if (this.actions().length >= 10) return;
    const config: Record<string, unknown> = {};
    if (action_type === 'reply_text') config['text'] = '';
    this.actions.update((arr) => [...arr, { action_type, action_config: config }]);
  }

  protected removeAction(idx: number): void {
    this.actions.update((arr) => arr.filter((_, i) => i !== idx));
  }

  protected updateActionConfig(idx: number, key: string, value: unknown): void {
    this.actions.update((arr) =>
      arr.map((a, i) =>
        i === idx ? { ...a, action_config: { ...a.action_config, [key]: value } } : a,
      ),
    );
  }

  protected actionConfigValue(action: ActionDraft, key: string): string {
    const v = action.action_config[key];
    return typeof v === 'string' ? v : '';
  }

  // --- save -------------------------------------------------------

  protected onSave(): void {
    if (this.saving()) return;
    const keywords = this.keywords();
    if (keywords.length === 0) {
      this.error.set('At least one keyword is required.');
      return;
    }
    if (!this.name().trim()) {
      this.error.set('Name is required.');
      return;
    }

    const payload: KeywordRuleUpsert = {
      name: this.name().trim(),
      keywords,
      match_type: this.matchType(),
      enabled: this.enabled(),
      priority: this.priority(),
      actions: this.actions().map<KeywordActionPayload>((a, idx) => ({
        action_type: a.action_type,
        action_config: a.action_config,
        position: idx,
      })),
    };
    this.saving.set(true);
    this.error.set(null);
    const id = this.editingId();
    const request$ = id ? this.api.update(id, payload) : this.api.create(payload);
    request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (rule) => {
        this.saving.set(false);
        this.saved.emit(rule);
      },
      error: (err: HttpErrorResponse) => {
        this.saving.set(false);
        this.error.set(extractApiError(err) ?? 'Could not save the rule.');
      },
    });
  }

  protected onCancel(): void {
    this.cancel.emit();
  }
}

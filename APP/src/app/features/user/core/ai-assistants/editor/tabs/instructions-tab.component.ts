/**
 * AI Instructions tab (``tasks/ai-assistants`` Step 8).
 *
 * Three grouped sections mirroring the Pabbly Chatflow reference:
 *
 *   1. **Prompt** — instruction-type dropdown (Custom + 6 seeded
 *      presets from `GET /templates?channel=ai_prompt`) + prompt
 *      textarea.
 *   2. **AI Configuration** — temperature slider, provider-key select
 *      (only shows configured keys with `test_status='success'`;
 *      empty state links to Settings → Integrations), model select.
 *   3. **Advanced** — stop-keywords chip input, retry attempts,
 *      fallback message, allowed-domains chip input, output-
 *      sanitiser toggle, budget-cap override.
 *
 * Every field two-way binds to :class:`AssistantFormStateService`.
 * The Save button in the editor header (Step 7) reads the merged
 * form-state and issues one PATCH; instruction changes trigger the
 * backend audit-log write via Step 6's service.
 */
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { AiProviderKey } from '../../../settings/integrations/ai-providers-api.service';
import { AiAssistantsApiService } from '../../ai-assistants-api.service';
import { AssistantFormStateService } from '../../form-state.service';
import { CUSTOM_PROMPT_ID, InstructionPreset } from '../../instructions-presets';

// v1 is OpenAI-only. Model list matches ``shared/llm/pricing.py``'s
// keys — when a new adapter ships, this list becomes provider-driven.
const OPENAI_MODELS: readonly string[] = ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'];

@Component({
  selector: 'app-ai-assistant-instructions-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule, RouterLink],
  templateUrl: './instructions-tab.component.html',
})
export class InstructionsTabComponent {
  private readonly api = inject(AiAssistantsApiService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly formState = inject(AssistantFormStateService);

  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  protected readonly presets = signal<InstructionPreset[]>([]);
  protected readonly keys = signal<AiProviderKey[]>([]);

  /** Currently-selected preset id in the dropdown. Not persisted
   *  server-side — selecting a preset is a one-shot COPY into the
   *  prompt textarea, so re-selecting the same preset re-copies. */
  protected readonly selectedPresetId = signal<string>(CUSTOM_PROMPT_ID);

  protected readonly models = OPENAI_MODELS;
  protected readonly customPromptId = CUSTOM_PROMPT_ID;

  /** Only surface keys that actually work — an untested / failed key
   *  in the dropdown would let an operator save an assistant that
   *  fails on first message. */
  protected readonly usableKeys = computed(() =>
    this.keys().filter((k) => !k.revoked_at && k.test_status === 'success'),
  );

  protected readonly hasUsableKey = computed(() => this.usableKeys().length > 0);

  constructor() {
    // Presets + keys are independent — kick off both requests in
    // parallel and set the two signals independently.
    this.api
      .listAiPromptPresets()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          const presets: InstructionPreset[] = [
            { id: CUSTOM_PROMPT_ID, label: 'Custom Prompt', body: '' },
            ...rows.map((r) => ({ id: r.id, label: r.name, body: r.body_text })),
          ];
          this.presets.set(presets);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load prompt presets.');
        },
      });
    this.api
      .listProviderKeys()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.keys.set(rows),
        error: () => this.keys.set([]),
      });
  }

  // --- Prompt section -----------------------------------------------

  protected onPresetChange(event: Event): void {
    const id = (event.target as HTMLSelectElement).value;
    this.selectedPresetId.set(id);
    if (id === CUSTOM_PROMPT_ID) return;
    const preset = this.presets().find((p) => p.id === id);
    if (!preset) return;
    // Copy — NOT bind. Operator can freely edit after paste, and
    // future edits to the preset library don't retroactively
    // change the assistant's prompt.
    this.formState.patch({ instructions: preset.body });
  }

  protected onInstructionsInput(event: Event): void {
    const value = (event.target as HTMLTextAreaElement).value;
    this.formState.patch({ instructions: value || null });
  }

  // --- AI Configuration section -------------------------------------

  protected onTemperatureInput(event: Event): void {
    const raw = Number((event.target as HTMLInputElement).value);
    const clamped = Number.isFinite(raw) ? Math.min(1, Math.max(0, raw)) : 0.5;
    this.formState.patch({ temperature: clamped });
  }

  protected onKeyChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.formState.patch({ key_id: value });
  }

  protected onModelChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.formState.patch({ model: value });
  }

  // --- Advanced section ---------------------------------------------

  protected addStopKeyword(event: KeyboardEvent): void {
    if (event.key !== 'Enter' && event.key !== ',') return;
    event.preventDefault();
    const input = event.target as HTMLInputElement;
    const raw = input.value.trim().replace(/,+$/, '');
    if (!raw) return;
    const current = this.formState.formState().stop_keywords;
    if (current.includes(raw)) {
      input.value = '';
      return;
    }
    if (current.length >= 32) return;
    this.formState.patch({ stop_keywords: [...current, raw] });
    input.value = '';
  }

  protected removeStopKeyword(kw: string): void {
    this.formState.patch({
      stop_keywords: this.formState.formState().stop_keywords.filter((k) => k !== kw),
    });
  }

  protected onRetryInput(event: Event): void {
    const raw = Number((event.target as HTMLInputElement).value);
    const clamped = Number.isFinite(raw) ? Math.min(5, Math.max(0, Math.round(raw))) : 0;
    this.formState.patch({ retry_attempts: clamped });
  }

  protected onFallbackInput(event: Event): void {
    const value = (event.target as HTMLTextAreaElement).value;
    this.formState.patch({ fallback_message: value });
  }

  protected addAllowedDomain(event: KeyboardEvent): void {
    if (event.key !== 'Enter' && event.key !== ',') return;
    event.preventDefault();
    const input = event.target as HTMLInputElement;
    const raw = input.value.trim().toLowerCase().replace(/,+$/, '');
    if (!raw) return;
    const current = this.formState.formState().allowed_domains;
    if (current.includes(raw)) {
      input.value = '';
      return;
    }
    if (current.length >= 64) return;
    this.formState.patch({ allowed_domains: [...current, raw] });
    input.value = '';
  }

  protected removeAllowedDomain(d: string): void {
    this.formState.patch({
      allowed_domains: this.formState.formState().allowed_domains.filter((x) => x !== d),
    });
  }

  protected onSanitizerToggle(event: Event): void {
    this.formState.patch({
      output_sanitizer_enabled: (event.target as HTMLInputElement).checked,
    });
  }

  protected onBudgetOverrideInput(event: Event): void {
    const raw = (event.target as HTMLInputElement).value.trim();
    if (!raw) {
      this.formState.patch({ budget_cap_override_usd: null });
      return;
    }
    const num = Number(raw);
    if (!Number.isFinite(num) || num < 0) return;
    this.formState.patch({ budget_cap_override_usd: num });
  }

  // --- Lead capture (Step 16) ---------------------------------------

  protected onLeadCaptureModeChange(event: Event): void {
    const raw = (event.target as HTMLSelectElement).value;
    // Restrict to the three legal values. Any other value would be
    // a UI drift and gets ignored client-side (backend enforces
    // via ENUM CHECK anyway).
    if (raw === 'off' || raw === 'detect_email' || raw === 'ask_at_turn') {
      this.formState.patch({ lead_capture_mode: raw });
    }
  }

  protected onLeadCaptureTurnInput(event: Event): void {
    const raw = Number((event.target as HTMLInputElement).value);
    const clamped = Number.isFinite(raw) ? Math.min(20, Math.max(1, Math.round(raw))) : 3;
    this.formState.patch({ lead_capture_turn_n: clamped });
  }

  protected onLeadCaptureMessageInput(event: Event): void {
    const value = (event.target as HTMLTextAreaElement).value;
    this.formState.patch({ lead_capture_message: value || null });
  }
}

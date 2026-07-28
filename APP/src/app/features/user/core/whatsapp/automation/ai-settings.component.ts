import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  AISettings,
  AISettingsPatch,
  WhatsAppAutomationApiService,
} from './whatsapp-automation-api.service';

/**
 * AI Settings tab (whatsapp-platform-upgrade Step 19).
 *
 * Edits the org-wide AI knobs that govern the WhatsApp AI agent:
 *   - default-enable on new conversations
 *   - confidence threshold (handover when below)
 *   - handover keywords (one per line)
 *   - optional system prompt
 *
 * Per-conversation toggle ("AI Handled" / "Needs Human") lives on
 * the chat-thread header and is unrelated to this surface.
 */
@Component({
  selector: 'app-ai-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  template: `
    <div class="space-y-4 rounded-md border border-subtle bg-surface p-4">
      <div class="flex items-center justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">AI agent settings</p>
          <p class="text-[11px] text-muted">
            Wires the per-conversation "AI Handled" toggle. Replies below the confidence threshold
            escalate to a human.
          </p>
        </div>
        @if (loading()) {
          <span class="text-[11px] text-muted">Loading…</span>
        }
      </div>

      @if (loadError(); as err) {
        <div class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {{ err }}
        </div>
      }
      @if (toast(); as msg) {
        <div class="rounded-md border border-subtle bg-surface-2 px-3 py-2 text-xs text-default">
          {{ msg }}
        </div>
      }

      <label class="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          [checked]="defaultEnabled()"
          (change)="defaultEnabled.set($any($event.target).checked)"
        />
        Auto-enable AI on every new WhatsApp conversation
      </label>

      <div>
        <label class="mb-1 block text-xs font-medium text-default">
          Confidence threshold ({{ threshold().toFixed(2) }})
        </label>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          [ngModel]="threshold()"
          (ngModelChange)="threshold.set(Number($event))"
          class="w-full"
        />
        <p class="mt-1 text-[10px] text-muted">
          Below this confidence, the AI escalates to a human. 0.6 is a conservative default; raise
          to 0.8 for very high-stakes businesses, lower to 0.4 if you trust the LLM more.
        </p>
      </div>

      <div>
        <label class="mb-1 block text-xs font-medium text-default">
          Handover keywords (one per line)
        </label>
        <p class="mb-2 text-[10px] text-muted">
          When the customer's message contains any of these phrases, the AI hands off to a human
          immediately — no LLM call.
        </p>
        <textarea
          [ngModel]="handoverKeywordsText()"
          (ngModelChange)="handoverKeywordsText.set($event)"
          rows="4"
          placeholder="talk to person&#10;agent please&#10;इंसान से बात"
          class="w-full rounded-md border border-subtle px-3 py-2 text-xs font-mono"
        ></textarea>
      </div>

      <div>
        <label class="mb-1 block text-xs font-medium text-default">
          System prompt (optional)
        </label>
        <p class="mb-2 text-[10px] text-muted">
          Persona / business context prepended to every AI call. Leave blank for the built-in
          baseline (polite, concise, defers to humans on prices).
        </p>
        <textarea
          [ngModel]="systemPrompt()"
          (ngModelChange)="systemPrompt.set($event)"
          rows="5"
          maxlength="4096"
          placeholder="You are the customer-service assistant for Sharma Furniture, a family-run furniture store in Mumbai since 1992…"
          class="w-full rounded-md border border-subtle px-3 py-2 text-sm"
        ></textarea>
        <p class="mt-1 text-right text-[10px] text-faint">{{ systemPrompt().length }}/4096</p>
      </div>

      <div class="flex justify-end">
        <button
          type="button"
          (click)="save()"
          [disabled]="saving() || loading()"
          class="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-white hover:bg-accent disabled:opacity-50"
        >
          {{ saving() ? 'Saving…' : 'Save AI settings' }}
        </button>
      </div>
    </div>
  `,
})
export class AISettingsComponent {
  private readonly api = inject(WhatsAppAutomationApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly Number = Number;

  protected readonly loading = signal<boolean>(false);
  protected readonly saving = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);

  protected readonly defaultEnabled = signal<boolean>(false);
  protected readonly threshold = signal<number>(0.6);
  protected readonly handoverKeywordsText = signal<string>('');
  protected readonly systemPrompt = signal<string>('');

  constructor() {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .getAISettings()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this.hydrate(s);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load AI settings.');
        },
      });
  }

  private hydrate(s: AISettings): void {
    this.defaultEnabled.set(s.ai_handling_default_enabled);
    this.threshold.set(s.ai_confidence_threshold);
    this.handoverKeywordsText.set((s.ai_handover_keywords || []).join('\n'));
    this.systemPrompt.set(s.ai_system_prompt || '');
  }

  protected save(): void {
    const keywords = this.handoverKeywordsText()
      .split('\n')
      .map((k) => k.trim())
      .filter((k) => k.length > 0);

    const payload: AISettingsPatch = {
      ai_handling_default_enabled: this.defaultEnabled(),
      ai_confidence_threshold: this.threshold(),
      ai_handover_keywords: keywords,
      ai_system_prompt: this.systemPrompt().trim() || null,
    };
    this.saving.set(true);
    this.toast.set(null);
    this.loadError.set(null);
    this.api
      .patchAISettings(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this.hydrate(s);
          this.saving.set(false);
          this.toast.set('AI settings saved.');
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not save AI settings.');
        },
      });
  }
}

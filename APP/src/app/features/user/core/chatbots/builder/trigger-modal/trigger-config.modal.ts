import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  HostListener,
  Input,
  Output,
  ViewChild,
  signal,
  inject,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { ConfirmDialogService } from '../../../shared/confirm-dialog/confirm-dialog.service';
import { MobileSelectComponent } from '../../../shared/forms/mobile-select.component';
import { TriggerConfig } from '../../chatbots-api.service';

const CHANNEL_OPTIONS = [
  { value: 'any', label: 'Any channel (WhatsApp + Email)' },
  { value: 'whatsapp', label: 'WhatsApp only' },
  { value: 'email', label: 'Email only' },
];

const MODE_OPTIONS = [
  { value: 'any', label: 'Any inbound message (no filter)' },
  { value: 'keyword', label: 'Keyword match' },
  { value: 'regex', label: 'Regex pattern' },
];

/**
 * Bot-trigger configuration modal (tasks/chatbot-builder Step 13 /
 * mockup.html).
 *
 * Opens from the always-present trigger card at the top of the
 * canvas. Emits `(save)` with the assembled TriggerConfig; the
 * builder page hands it off to `canvasState.setTriggerConfig`.
 */
@Component({
  selector: 'app-chatbot-trigger-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule, MobileSelectComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      (click)="onBackdropClick($event)"
    >
      <div
        class="bg-surface border border-subtle rounded-xl w-[520px] max-w-[92vw] shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cb_trigger_title"
        (click)="$event.stopPropagation()"
      >
        <header class="flex items-center gap-3 px-5 py-4 border-b border-subtle">
          <span
            class="w-8 h-8 rounded-lg bg-accent-soft text-accent inline-flex items-center justify-center"
          >
            <lucide-icon name="zap" size="16"></lucide-icon>
          </span>
          <div class="flex-1">
            <h2 id="cb_trigger_title" class="text-sm font-semibold text-default">Trigger</h2>
            <p class="text-[11px] text-muted mt-0.5">When should this bot start?</p>
          </div>
          <button
            type="button"
            (click)="requestClose()"
            class="p-1.5 rounded hover:bg-surface-2 text-muted hover:text-default"
            aria-label="Close"
          >
            <lucide-icon name="x" size="16"></lucide-icon>
          </button>
        </header>

        <div class="px-5 py-5 space-y-4">
          <div>
            <label class="block text-[11px] font-medium text-muted mb-1.5 uppercase tracking-wide"
              >Channel</label
            >
            <crm-mobile-select
              [options]="channelOptions"
              [value]="channel()"
              (valueChange)="channel.set($any($event))"
            />
          </div>

          <div>
            <label class="block text-[11px] font-medium text-muted mb-1.5 uppercase tracking-wide"
              >Match mode</label
            >
            <crm-mobile-select
              [options]="modeOptions"
              [value]="mode()"
              (valueChange)="mode.set($any($event))"
            />
            <p class="text-[11px] text-muted mt-1">
              Keyword match covers most bots. Use regex only for advanced patterns.
            </p>
          </div>

          @if (mode() === 'any') {
            <div
              class="rounded-md border border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300 p-3 text-[11px] leading-relaxed"
            >
              <div class="flex items-start gap-2">
                <lucide-icon
                  name="alert-triangle"
                  size="14"
                  class="flex-shrink-0 mt-0.5"
                ></lucide-icon>
                <div>
                  <strong class="font-semibold">This bot fires on every inbound message.</strong>
                  Any AI Assistant bound to the same channel will never respond — this bot takes
                  every message. Add a <em>Route to AI</em> node inside your flow if you want the AI
                  to answer specific branches.
                </div>
              </div>
            </div>
          }

          @if (mode() === 'keyword') {
            <div>
              <label class="block text-[11px] font-medium text-muted mb-1.5 uppercase tracking-wide"
                >Keywords</label
              >
              <div
                class="flex flex-wrap gap-1.5 p-2 bg-app border border-subtle rounded-md min-h-[38px]"
              >
                @for (kw of keywords(); track kw) {
                  <span
                    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-accent-soft text-accent"
                  >
                    {{ kw }}
                    <button
                      type="button"
                      (click)="removeKeyword(kw)"
                      class="opacity-70 hover:opacity-100"
                      aria-label="Remove keyword"
                    >
                      ×
                    </button>
                  </span>
                }
                <input
                  #kwInput
                  type="text"
                  placeholder="Add keyword, press Enter or comma"
                  (keydown.enter)="addKeyword(kwInput.value); kwInput.value = ''"
                  (keydown.comma)="
                    addKeyword(kwInput.value); kwInput.value = ''; $event.preventDefault()
                  "
                  (blur)="addKeyword(kwInput.value); kwInput.value = ''"
                  class="flex-1 min-w-[100px] bg-transparent text-xs text-default focus:outline-none"
                />
              </div>
              <p class="text-[11px] text-muted mt-1">
                Type each keyword and press Enter, or separate with commas. Matching is
                word-boundary — "hi" won't match "hii".
              </p>
            </div>
          }

          @if (mode() === 'regex') {
            <div>
              <label class="block text-[11px] font-medium text-muted mb-1.5 uppercase tracking-wide"
                >Regex pattern</label
              >
              <input
                type="text"
                [ngModel]="regexPattern()"
                (ngModelChange)="regexPattern.set($event)"
                placeholder="^(help|support)"
                maxlength="500"
                class="w-full px-3 py-2 text-xs font-mono bg-app text-default border border-subtle rounded-md focus:outline-none focus:border-accent"
              />
              <p class="text-[11px] text-muted mt-1">
                Max 500 chars. Runs on the first 4 KB of every inbound message.
              </p>
            </div>
          }

          @if (validationError(); as v) {
            <p
              class="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-700 dark:text-red-300"
              role="alert"
            >
              {{ v }}
            </p>
          }

          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-xs text-default">Case sensitive</div>
              <div class="text-[11px] text-muted">"HEY" matches "hey" when off.</div>
            </div>
            <input
              type="checkbox"
              [checked]="caseSensitive()"
              (change)="caseSensitive.set(!caseSensitive())"
              class="h-4 w-4 accent-current"
              aria-label="Case sensitive"
            />
          </div>

          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-xs text-default">First message only</div>
              <div class="text-[11px] text-muted">
                Fire only on the customer's first-ever message.
              </div>
            </div>
            <input
              type="checkbox"
              [checked]="firstMessageOnly()"
              (change)="firstMessageOnly.set(!firstMessageOnly())"
              class="h-4 w-4 accent-current"
              aria-label="First message only"
            />
          </div>
        </div>

        <footer class="flex justify-end gap-2 px-5 py-3 border-t border-subtle">
          <button
            type="button"
            (click)="requestClose()"
            class="px-3.5 py-1.5 text-xs font-medium text-muted hover:text-default"
          >
            Cancel
          </button>
          <button
            type="button"
            (click)="onSave()"
            class="px-3.5 py-1.5 text-xs font-semibold bg-accent-soft text-accent hover:brightness-110 rounded-md"
          >
            Save trigger
          </button>
        </footer>
      </div>
    </div>
  `,
})
export class TriggerConfigModalComponent {
  private readonly confirmDialog = inject(ConfirmDialogService);
  private _initial: TriggerConfig | null = null;
  /** True while the discard confirm is up, so Esc doesn't stack. */
  private confirming = false;

  /** Inline reason Save was refused (set by `onSave`). */
  readonly validationError = signal<string | null>(null);

  @Input({ required: true })
  set config(value: TriggerConfig) {
    this._initial = value;
    this.channel.set(value.channel);
    this.mode.set(value.mode);
    this.keywords.set([...(value.keywords ?? [])]);
    this.regexPattern.set(value.regex_pattern ?? '');
    this.caseSensitive.set(!!value.case_sensitive);
    this.firstMessageOnly.set(!!value.first_message_only);
  }

  @Output() save = new EventEmitter<TriggerConfig>();
  @Output() close = new EventEmitter<void>();

  readonly channelOptions = CHANNEL_OPTIONS;
  readonly modeOptions = MODE_OPTIONS;

  readonly channel = signal<TriggerConfig['channel']>('any');
  readonly mode = signal<TriggerConfig['mode']>('any');
  readonly keywords = signal<string[]>([]);
  readonly regexPattern = signal<string>('');
  readonly caseSensitive = signal<boolean>(false);
  readonly firstMessageOnly = signal<boolean>(false);

  /** Reference to the keyword-entry input so `onSave` can flush any
   *  typed-but-not-Enter-submitted text into the list before emitting
   *  the config. Without this, "hi" typed into the box + click Save
   *  silently drops the value. */
  @ViewChild('kwInput') private kwInputRef?: ElementRef<HTMLInputElement>;

  addKeyword(raw: string): void {
    // Split on commas so operators can type or paste multiple keywords
    // at once ("hi, hello, hey") without remembering to press Enter
    // between each — the previous behaviour stored the joined string as
    // one keyword and silently broke trigger matching.
    const parts = (raw ?? '')
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    if (parts.length === 0) return;
    this.keywords.update((rows) => {
      const seen = new Set(rows);
      const next = [...rows];
      for (const p of parts) {
        if (!seen.has(p)) {
          seen.add(p);
          next.push(p);
        }
      }
      return next;
    });
  }

  removeKeyword(kw: string): void {
    this.keywords.update((rows) => rows.filter((k) => k !== kw));
  }

  onBackdropClick(evt: MouseEvent): void {
    if (evt.target !== evt.currentTarget) return;
    void this.requestClose();
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (!this.confirming) void this.requestClose();
  }

  /** Cancel / ✕ / Esc / backdrop — asks before discarding edits. */
  async requestClose(): Promise<void> {
    if (this.isChanged()) {
      this.confirming = true;
      try {
        const ok = await this.confirmDialog.ask({
          title: 'Discard trigger changes?',
          body: 'Your edits to this trigger will be lost.',
          confirmLabel: 'Discard',
          danger: true,
        });
        if (!ok) return;
      } finally {
        this.confirming = false;
      }
    }
    this.close.emit();
  }

  /** Any difference from the config the modal opened with (including a
   *  keyword typed but not yet added). */
  private isChanged(): boolean {
    const init = this._initial;
    if (!init) return false;
    const pending = this.kwInputRef?.nativeElement.value.trim() ?? '';
    return (
      pending !== '' ||
      this.channel() !== init.channel ||
      this.mode() !== init.mode ||
      JSON.stringify(this.keywords()) !== JSON.stringify(init.keywords ?? []) ||
      this.regexPattern() !== (init.regex_pattern ?? '') ||
      this.caseSensitive() !== !!init.case_sensitive ||
      this.firstMessageOnly() !== !!init.first_message_only
    );
  }

  onSave(): void {
    // Flush any typed-but-not-Enter-submitted keyword before building
    // the payload. The keyword input is uncontrolled; without this
    // the operator's last word gets dropped on the floor.
    if (this.mode() === 'keyword' && this.kwInputRef) {
      const pending = this.kwInputRef.nativeElement.value;
      if (pending.trim()) {
        this.addKeyword(pending);
        this.kwInputRef.nativeElement.value = '';
      }
    }
    if (this.mode() === 'keyword' && this.keywords().length === 0) {
      this.validationError.set('Add at least one keyword — or switch to "Any inbound message".');
      return;
    }
    if (this.mode() === 'regex' && !this.regexPattern().trim()) {
      this.validationError.set('Enter a regex pattern — or switch match mode.');
      return;
    }
    this.validationError.set(null);
    const cfg: TriggerConfig = {
      channel: this.channel(),
      mode: this.mode(),
      keywords: this.mode() === 'keyword' ? this.keywords() : [],
      regex_pattern: this.mode() === 'regex' ? this.regexPattern().trim() || null : null,
      case_sensitive: this.caseSensitive(),
      first_message_only: this.firstMessageOnly(),
    };
    this.save.emit(cfg);
  }
}

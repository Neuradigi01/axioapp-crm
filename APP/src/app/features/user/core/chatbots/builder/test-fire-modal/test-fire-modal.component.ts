import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  HostListener,
  Input,
  Output,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { MobileSelectComponent } from '../../../shared/forms/mobile-select.component';
import { ChatbotsApiService, TestFireResponse, TriggerConfig } from '../../chatbots-api.service';
import { humanizeKey, nodeTypeLabel } from '../node-type-registry';

/**
 * Test-fire modal — sends a fake inbound message through the bot in
 * dry-run mode and renders the resulting per-node transcript so the
 * operator can debug their graph without touching WhatsApp.
 *
 * Backend endpoint: `POST /chatbots/:id/test-fire`. The run is marked
 * `is_test=true` — no outbound sends, save-to writes land in a per-
 * run scratch, and the run row is swept after 24 h.
 */
@Component({
  selector: 'app-chatbot-test-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule, MobileSelectComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './test-fire-modal.component.html',
})
export class ChatbotTestFireModalComponent {
  private readonly api = inject(ChatbotsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input({ required: true }) botId!: string;
  @Input({ required: true }) triggerConfig!: TriggerConfig | null;

  @Output() readonly close = new EventEmitter<void>();

  readonly message = signal<string>('');
  readonly channel = signal<'whatsapp' | 'email'>('whatsapp');
  readonly firstMessage = signal<boolean>(false);

  readonly running = signal<boolean>(false);
  readonly error = signal<string | null>(null);
  readonly result = signal<TestFireResponse | null>(null);

  readonly channelOptions = [
    { value: 'whatsapp', label: 'WhatsApp' },
    { value: 'email', label: 'Email' },
  ];

  /** Suggest the trigger's keywords as one-click chips so the
   *  operator can test a matching phrase with zero typing. Only
   *  applies when the trigger is keyword-mode. */
  get suggestedKeywords(): string[] {
    if (!this.triggerConfig || this.triggerConfig.mode !== 'keyword') return [];
    return this.triggerConfig.keywords ?? [];
  }

  applySuggestion(kw: string): void {
    this.message.set(kw);
  }

  run(): void {
    if (this.running()) return;
    const text = this.message();
    if (!text || !text.trim()) {
      this.error.set('Type a message to simulate.');
      return;
    }
    this.running.set(true);
    this.error.set(null);
    this.result.set(null);
    this.api
      .testFire(this.botId, {
        simulated_inbound_text: text,
        simulated_channel: this.channel(),
        simulated_is_first_message: this.firstMessage(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.result.set(res);
          this.running.set(false);
        },
        error: (err) => {
          this.error.set(extractApiError(err) ?? 'Test fire failed.');
          this.running.set(false);
        },
      });
  }

  reset(): void {
    this.result.set(null);
    this.error.set(null);
  }

  onBackdropClick(evt: MouseEvent): void {
    if (evt.target === evt.currentTarget && !this.running()) this.close.emit();
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (!this.running()) this.close.emit();
  }

  protected readonly humanize = humanizeKey;
  protected readonly nodeLabel = nodeTypeLabel;

  statusTone(status: string): string {
    switch (status) {
      case 'completed':
        return 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300';
      case 'errored':
        return 'bg-red-500/15 text-red-700 dark:text-red-300';
      case 'parked':
        return 'bg-amber-500/15 text-amber-700 dark:text-amber-300';
      case 'canceled':
        return 'bg-zinc-500/15 text-muted';
      default:
        return 'bg-surface-2 text-default';
    }
  }

  stepTone(status: string): string {
    switch (status) {
      case 'completed':
        return 'text-emerald-600 dark:text-emerald-400';
      case 'errored':
        return 'text-red-600 dark:text-red-400';
      case 'skipped':
        return 'text-amber-700 dark:text-amber-300';
      default:
        return 'text-muted';
    }
  }
}

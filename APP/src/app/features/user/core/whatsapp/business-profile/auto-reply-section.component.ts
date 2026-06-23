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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  WhatsAppTemplateRead,
  WhatsAppTemplatesApiService,
} from '../templates/whatsapp-templates-api.service';
import {
  AutoReplySettings,
  AutoReplySettingsPatch,
  WhatsAppBusinessProfileApiService,
} from './whatsapp-business-profile-api.service';

/**
 * Auto-reply settings section
 * (whatsapp-platform-upgrade Step 16).
 *
 * Embedded inside the business-profile page (Step 11). Two cards —
 * Greeting + Away — each with:
 *   - enable toggle
 *   - free-text body (used in-session) with variable inserter
 *   - linked approved template (used out-of-session)
 *
 * Saves are independent of the parent page's profile save — small
 * surface, dedicated endpoints. Server enforces "if enabled, must
 * have body OR template" and returns 400 if not.
 */
@Component({
  selector: 'app-auto-reply-section',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  template: `
    <div class="rounded-md border border-zinc-200 bg-white p-4">
      <div class="mb-3 flex items-center justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Auto-replies
          </p>
          <p class="text-[11px] text-zinc-500">
            Fired on inbound messages. Cooldown: one per contact per
            type per 24 hours.
          </p>
        </div>
        @if (loading()) {
          <span class="text-[11px] text-zinc-500">Loading…</span>
        }
      </div>

      @if (loadError(); as err) {
        <div class="mb-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {{ err }}
        </div>
      }

      @if (toast(); as msg) {
        <div class="mb-3 rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-700">
          {{ msg }}
        </div>
      }

      <!-- Greeting card -->
      <div class="mb-4 rounded-md border border-zinc-200 p-3">
        <div class="mb-2 flex items-center justify-between">
          <label class="flex items-center gap-2 text-sm font-medium text-zinc-800">
            <input
              type="checkbox"
              [checked]="greetingEnabled()"
              (change)="greetingEnabled.set($any($event.target).checked)"
            />
            Greeting (first-time contact)
          </label>
          <p class="text-[10px] text-zinc-500">
            Sent once per contact per 24 hr.
          </p>
        </div>
        <textarea
          [ngModel]="greetingMessage()"
          (ngModelChange)="greetingMessage.set($event)"
          rows="2"
          maxlength="4096"
          placeholder="Hello {{ '{{contact.first_name}}' }}, welcome to {{ '{{org.name}}' }}!"
          class="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm"
        ></textarea>
        <div class="mt-1 flex flex-wrap gap-1">
          <button
            type="button"
            (click)="insertGreetingVar('contact.first_name')"
            class="rounded bg-zinc-100 px-2 py-0.5 text-[10px] text-zinc-700 hover:bg-zinc-200"
          >
            + contact.first_name
          </button>
          <button
            type="button"
            (click)="insertGreetingVar('contact.full_name')"
            class="rounded bg-zinc-100 px-2 py-0.5 text-[10px] text-zinc-700 hover:bg-zinc-200"
          >
            + contact.full_name
          </button>
          <button
            type="button"
            (click)="insertGreetingVar('org.name')"
            class="rounded bg-zinc-100 px-2 py-0.5 text-[10px] text-zinc-700 hover:bg-zinc-200"
          >
            + org.name
          </button>
        </div>
        <label class="mb-1 mt-3 block text-[11px] font-medium text-zinc-600">
          Fallback template (out-of-session)
        </label>
        <select
          [ngModel]="greetingTemplateId()"
          (ngModelChange)="greetingTemplateId.set($event || null)"
          class="w-full rounded-md border border-zinc-300 px-2 py-1.5 text-xs"
        >
          <option [ngValue]="null">— None —</option>
          @for (t of approvedTemplates(); track t.id) {
            <option [ngValue]="t.id">
              {{ t.name }} ({{ t.language }})
            </option>
          }
        </select>
        <p class="mt-1 text-[10px] text-zinc-500">
          Used when the contact is outside their 24-hour session window.
          Only approved templates appear.
        </p>
      </div>

      <!-- Away card -->
      <div class="mb-4 rounded-md border border-zinc-200 p-3">
        <div class="mb-2 flex items-center justify-between">
          <label class="flex items-center gap-2 text-sm font-medium text-zinc-800">
            <input
              type="checkbox"
              [checked]="awayEnabled()"
              (change)="awayEnabled.set($any($event.target).checked)"
            />
            Out-of-hours auto-reply
          </label>
          <p class="text-[10px] text-zinc-500">
            Fires outside business hours (set above).
          </p>
        </div>
        <textarea
          [ngModel]="awayMessage()"
          (ngModelChange)="awayMessage.set($event)"
          rows="2"
          maxlength="4096"
          placeholder="Thanks {{ '{{contact.first_name}}' }} — we're closed right now and will reply during business hours."
          class="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm"
        ></textarea>
        <div class="mt-1 flex flex-wrap gap-1">
          <button
            type="button"
            (click)="insertAwayVar('contact.first_name')"
            class="rounded bg-zinc-100 px-2 py-0.5 text-[10px] text-zinc-700 hover:bg-zinc-200"
          >
            + contact.first_name
          </button>
          <button
            type="button"
            (click)="insertAwayVar('org.name')"
            class="rounded bg-zinc-100 px-2 py-0.5 text-[10px] text-zinc-700 hover:bg-zinc-200"
          >
            + org.name
          </button>
        </div>
        <label class="mb-1 mt-3 block text-[11px] font-medium text-zinc-600">
          Fallback template (out-of-session)
        </label>
        <select
          [ngModel]="awayTemplateId()"
          (ngModelChange)="awayTemplateId.set($event || null)"
          class="w-full rounded-md border border-zinc-300 px-2 py-1.5 text-xs"
        >
          <option [ngValue]="null">— None —</option>
          @for (t of approvedTemplates(); track t.id) {
            <option [ngValue]="t.id">
              {{ t.name }} ({{ t.language }})
            </option>
          }
        </select>
      </div>

      <div class="flex justify-end">
        <button
          type="button"
          (click)="save()"
          [disabled]="saving() || loading()"
          class="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-semibold text-white hover:bg-zinc-800 disabled:opacity-50"
        >
          {{ saving() ? 'Saving…' : 'Save auto-replies' }}
        </button>
      </div>
    </div>
  `,
})
export class AutoReplySectionComponent {
  private readonly api = inject(WhatsAppBusinessProfileApiService);
  private readonly templatesApi = inject(WhatsAppTemplatesApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal<boolean>(false);
  protected readonly saving = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);

  protected readonly greetingEnabled = signal<boolean>(false);
  protected readonly greetingMessage = signal<string>('');
  protected readonly greetingTemplateId = signal<string | null>(null);

  protected readonly awayEnabled = signal<boolean>(false);
  protected readonly awayMessage = signal<string>('');
  protected readonly awayTemplateId = signal<string | null>(null);

  protected readonly templates = signal<WhatsAppTemplateRead[]>([]);
  protected readonly approvedTemplates = computed(() =>
    this.templates().filter((t) => t.submission_status === 'approved'),
  );

  constructor() {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .getAutoReplySettings()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this.hydrate(s);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load auto-reply settings.',
          );
        },
      });
    this.templatesApi
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.templates.set(rows),
        // Silent: empty template list just means the picker shows
        // only "— None —" which is the right empty state.
        error: () => this.templates.set([]),
      });
  }

  private hydrate(s: AutoReplySettings): void {
    this.greetingEnabled.set(s.greeting_enabled);
    this.greetingMessage.set(s.greeting_message || '');
    this.greetingTemplateId.set(s.greeting_template_id);
    this.awayEnabled.set(s.away_enabled);
    this.awayMessage.set(s.away_message || '');
    this.awayTemplateId.set(s.away_template_id);
  }

  protected save(): void {
    const payload: AutoReplySettingsPatch = {
      greeting_enabled: this.greetingEnabled(),
      greeting_message: this.greetingMessage() || null,
      greeting_template_id: this.greetingTemplateId(),
      away_enabled: this.awayEnabled(),
      away_message: this.awayMessage() || null,
      away_template_id: this.awayTemplateId(),
    };
    this.saving.set(true);
    this.toast.set(null);
    this.loadError.set(null);
    this.api
      .patchAutoReplySettings(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this.hydrate(s);
          this.saving.set(false);
          this.toast.set('Auto-reply settings saved.');
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not save auto-reply settings.',
          );
        },
      });
  }

  protected insertGreetingVar(name: string): void {
    this.greetingMessage.update((v) => `${v}{{${name}}}`);
  }

  protected insertAwayVar(name: string): void {
    this.awayMessage.update((v) => `${v}{{${name}}}`);
  }
}

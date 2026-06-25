import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import type { TemplateChannel } from '../templates-api.service';

/**
 * Generic preview pane — resolves dot-path `{{a.b.c}}` against a
 * fixed sample context and renders one of two shapes:
 *
 *   - WhatsApp: chat-bubble approximation (white bubble on the
 *     WA-green dotted background, with header / body / footer text).
 *   - Email: subject + body in a light-bordered "letter" card with
 *     monospace body (HTML rendering deferred — Step 7 ships the
 *     plain-text fallback so the operator at least sees how variables
 *     resolve).
 *
 * SMS / FB / IG / push fall through to a simple body-only card.
 *
 * The sample context is hard-coded for v1 — the test-send modal
 * (Step 8) is where the operator picks real recipient data.
 */
const SAMPLE_CONTEXT: Record<string, Record<string, string>> = {
  contact: {
    first_name: 'Asha',
    last_name: 'Mehta',
    full_name: 'Asha Mehta',
    email: 'asha@example.com',
    phone: '+91 98765 43210',
  },
  org: {
    name: 'Acme Furniture',
    support_email: 'support@acme.example',
    support_phone: '+91 80000 00000',
    address: '12 Brigade Road, Bengaluru',
    website: 'https://acme.example',
  },
  sender: {
    name: 'Rahul Patel',
    email: 'rahul@acme.example',
    role: 'Sales Manager',
    signature: 'Rahul Patel · Acme Furniture',
  },
  lead: {
    source: 'Website',
    status: 'Qualified',
    score: '78',
    estimated_value: '₹45,000',
    owner_name: 'Rahul Patel',
  },
  user: {
    full_name: 'Asha Mehta',
    email: 'asha@example.com',
    role: 'Owner',
  },
  appointment: {
    scheduled_at: 'Mon, 15 Jul · 11:00 AM',
    location: 'Bengaluru Showroom',
    notes: 'Bring fabric swatches',
  },
  quote: {
    id: 'Q-2026-1042',
    total_amount: '₹45,000',
    currency: 'INR',
    expires_at: '12 Jul 2026',
    pdf_url: 'https://acme.example/quotes/1042.pdf',
  },
  invoice: {
    id: 'INV-2026-0421',
    total_amount: '₹45,000',
    currency: 'INR',
    due_date: '30 Jul 2026',
    pdf_url: 'https://acme.example/invoices/0421.pdf',
  },
};

const VAR_RE = /\{\{\s*([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*)\s*\}\}/g;


@Component({
  selector: 'app-preview-pane',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  template: `
    @switch (channel()) {
      @case ('whatsapp') {
        <div
          class="rounded-2xl border border-zinc-200 bg-[#e5ddd5] p-4 shadow-inner"
          style="min-height: 320px; background-image: radial-gradient(circle, rgba(0,0,0,0.04) 1px, transparent 1px); background-size: 12px 12px;"
        >
          <p class="mb-2 text-center text-[10px] font-medium uppercase tracking-wide text-zinc-600">
            Preview
          </p>
          <div class="flex justify-start">
            <div
              class="max-w-[85%] rounded-2xl rounded-tl-sm bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm"
            >
              @if (resolvedBody()) {
                <p class="whitespace-pre-wrap break-words text-sm">
                  {{ resolvedBody() }}
                </p>
              } @else {
                <p class="text-xs italic text-zinc-400">
                  Body text will appear here…
                </p>
              }
            </div>
          </div>
        </div>
      }
      @case ('email') {
        <div class="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm">
          <p class="mb-2 text-[10px] font-medium uppercase tracking-wide text-zinc-500">
            Preview
          </p>
          @if (resolvedSubject(); as s) {
            <div class="mb-2 border-b border-zinc-100 pb-2">
              <p class="text-[10px] uppercase tracking-wide text-zinc-400">Subject</p>
              <p class="text-sm font-semibold text-zinc-900">{{ s }}</p>
            </div>
          }
          @if (resolvedBody()) {
            <pre class="whitespace-pre-wrap break-words font-sans text-sm text-zinc-800">{{ resolvedBody() }}</pre>
          } @else {
            <p class="text-xs italic text-zinc-400">
              Body will appear here as you type…
            </p>
          }
        </div>
      }
      @default {
        <div class="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm">
          <p class="mb-2 text-[10px] font-medium uppercase tracking-wide text-zinc-500">
            Preview
          </p>
          @if (resolvedBody()) {
            <p class="whitespace-pre-wrap break-words text-sm text-zinc-800">
              {{ resolvedBody() }}
            </p>
          } @else {
            <p class="text-xs italic text-zinc-400">Body will appear here…</p>
          }
        </div>
      }
    }
  `,
})
export class PreviewPaneComponent {
  readonly channel = input.required<TemplateChannel>();
  readonly subject = input<string | null>(null);
  readonly body = input<string>('');

  protected readonly resolvedSubject = computed(() => {
    const s = this.subject();
    return s ? this.resolve(s) : null;
  });

  protected readonly resolvedBody = computed(() => this.resolve(this.body()));

  private resolve(text: string): string {
    if (!text) return '';
    return text.replace(VAR_RE, (_match, path: string) => {
      const segments = path.split('.');
      let cursor: unknown = SAMPLE_CONTEXT;
      for (const seg of segments) {
        if (
          cursor !== null &&
          typeof cursor === 'object' &&
          seg in (cursor as Record<string, unknown>)
        ) {
          cursor = (cursor as Record<string, unknown>)[seg];
        } else {
          return '';
        }
      }
      return typeof cursor === 'string' ? cursor : '';
    });
  }
}

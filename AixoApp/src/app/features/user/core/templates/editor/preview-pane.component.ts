import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import type { TemplateChannel, WhatsAppTemplateButton } from '../templates-api.service';

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
          class="rounded-2xl border border-subtle bg-[#e5ddd5] p-4 shadow-inner"
          style="min-height: 320px; background-image: radial-gradient(circle, rgba(0,0,0,0.04) 1px, transparent 1px); background-size: 12px 12px;"
        >
          <p class="mb-2 text-center text-[10px] font-medium uppercase tracking-wide text-muted">
            Preview
          </p>
          <div class="flex flex-col items-start gap-1">
            <div
              class="max-w-[85%] overflow-hidden rounded-2xl rounded-tl-sm bg-surface text-sm text-default shadow-sm"
            >
              @if (waHeaderType() === 'text' && resolvedHeader()) {
                <p class="px-3 pt-2 text-sm font-semibold text-default">
                  {{ resolvedHeader() }}
                </p>
              } @else if (waHeaderType() === 'image') {
                <div
                  class="flex h-24 items-center justify-center bg-surface-2 text-[10px] uppercase tracking-wide text-muted"
                >
                  Image header
                </div>
              } @else if (waHeaderType() === 'video') {
                <div
                  class="flex h-24 items-center justify-center bg-surface-2 text-[10px] uppercase tracking-wide text-muted"
                >
                  Video header
                </div>
              } @else if (waHeaderType() === 'document') {
                <div
                  class="flex h-16 items-center justify-center bg-surface-2 text-[10px] uppercase tracking-wide text-muted"
                >
                  Document header
                </div>
              }

              @if (resolvedBody()) {
                <p class="whitespace-pre-wrap break-words px-3 py-2 text-sm">
                  {{ resolvedBody() }}
                </p>
              } @else {
                <p class="px-3 py-2 text-xs italic text-faint">Body text will appear here…</p>
              }

              @if (waFooter()) {
                <p class="px-3 pb-2 text-[11px] text-muted">{{ waFooter() }}</p>
              }
            </div>

            @if (waButtons().length > 0) {
              <div class="flex w-full max-w-[85%] flex-col gap-1">
                @for (btn of waButtons(); track $index) {
                  <button
                    type="button"
                    class="flex items-center justify-center gap-1.5 rounded-lg bg-surface px-3 py-2 text-sm font-medium text-[#0088cc] shadow-sm"
                    tabindex="-1"
                  >
                    @if (btn.type === 'url') {
                      <lucide-icon name="external-link" size="14" aria-hidden="true"></lucide-icon>
                    } @else if (btn.type === 'phone_number') {
                      <lucide-icon name="phone" size="14" aria-hidden="true"></lucide-icon>
                    } @else {
                      <lucide-icon name="corner-up-left" size="14" aria-hidden="true"></lucide-icon>
                    }
                    <span>{{ btn.text || '(button label)' }}</span>
                  </button>
                }
              </div>
            }
          </div>
        </div>
      }
      @case ('email') {
        <div class="rounded-lg border border-subtle bg-surface p-4 shadow-sm">
          <p class="mb-2 text-[10px] font-medium uppercase tracking-wide text-muted">Preview</p>
          @if (resolvedSubject(); as s) {
            <div class="mb-2 border-b border-subtle pb-2">
              <p class="text-[10px] uppercase tracking-wide text-faint">Subject</p>
              <p class="text-sm font-semibold text-default">{{ s }}</p>
            </div>
          }
          @if (resolvedBody()) {
            <pre class="whitespace-pre-wrap break-words font-sans text-sm text-default">{{
              resolvedBody()
            }}</pre>
          } @else {
            <p class="text-xs italic text-faint">Body will appear here as you type…</p>
          }
        </div>
      }
      @default {
        <div class="rounded-lg border border-subtle bg-surface p-4 shadow-sm">
          <p class="mb-2 text-[10px] font-medium uppercase tracking-wide text-muted">Preview</p>
          @if (resolvedBody()) {
            <p class="whitespace-pre-wrap break-words text-sm text-default">
              {{ resolvedBody() }}
            </p>
          } @else {
            <p class="text-xs italic text-faint">Body will appear here…</p>
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
  // WhatsApp-specific extras. All optional — the preview falls back
  // to the plain body-only bubble when nothing is supplied so non-WA
  // channels are unaffected.
  readonly waHeaderType = input<'' | 'text' | 'image' | 'video' | 'document'>('');
  readonly waHeaderText = input<string>('');
  readonly waFooter = input<string>('');
  readonly waButtons = input<WhatsAppTemplateButton[]>([]);

  protected readonly resolvedSubject = computed(() => {
    const s = this.subject();
    return s ? this.resolve(s) : null;
  });

  protected readonly resolvedBody = computed(() => this.resolve(this.body()));
  protected readonly resolvedHeader = computed(() => this.resolve(this.waHeaderText()));

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

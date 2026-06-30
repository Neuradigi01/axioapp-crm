import { CommonModule } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { environment } from '../../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';

interface AttributionResponse {
  conversation_id: string;
  source: string | null;
  campaign_id: string | null;
  campaign_name: string | null;
  ad_id: string | null;
  ad_name: string | null;
  landing_url: string | null;
  deeplink: string | null;
  payload: Record<string, unknown>;
}

/**
 * Click-to-WhatsApp attribution chip on the chat-thread header
 * (whatsapp-platform-upgrade Step 24).
 *
 * Renders the friendly campaign name when available; falls back
 * to "From: Meta Ad" when only an ad_id was captured. Clicking
 * the chip opens the Meta Ads Manager deeplink in a new tab.
 *
 * The chip is hidden entirely for organic conversations — no
 * banner clutter when there's nothing to attribute.
 */
@Component({
  selector: 'app-attribution-chip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  template: `
    @if (attribution(); as a) {
      @if (a.source === 'ad') {
        @if (a.deeplink) {
          <a
            [href]="a.deeplink"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-1 rounded-full bg-violet-50 px-2.5 py-1 text-xs font-medium text-violet-700 ring-1 ring-violet-200 hover:bg-violet-100"
            [title]="hoverText(a)"
          >
            <lucide-icon name="megaphone" class="h-3 w-3" />
            {{ chipText(a) }}
            <lucide-icon name="external-link" class="h-3 w-3 opacity-60" />
          </a>
        } @else {
          <span
            class="inline-flex items-center gap-1 rounded-full bg-violet-50 px-2.5 py-1 text-xs font-medium text-violet-700 ring-1 ring-violet-200"
            [title]="hoverText(a)"
          >
            <lucide-icon name="megaphone" class="h-3 w-3" />
            {{ chipText(a) }}
          </span>
        }
      }
    }
  `,
})
export class AttributionChipComponent {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);

  readonly conversationId = input.required<string>();

  protected readonly attribution = signal<AttributionResponse | null>(null);

  constructor() {
    effect(() => {
      const id = this.conversationId();
      if (id) this.load(id);
    });
  }

  protected chipText(a: AttributionResponse): string {
    if (a.campaign_name) return `From: Meta Ad — ${a.campaign_name}`;
    if (a.ad_name) return `From: Meta Ad — ${a.ad_name}`;
    return 'From: Meta Ad';
  }

  protected hoverText(a: AttributionResponse): string {
    const parts: string[] = [];
    if (a.campaign_name) parts.push(`Campaign: ${a.campaign_name}`);
    if (a.ad_name) parts.push(`Ad: ${a.ad_name}`);
    if (a.ad_id) parts.push(`Ad id: ${a.ad_id}`);
    if (a.landing_url) parts.push(`Landing: ${a.landing_url}`);
    parts.push('Click to open in Meta Ads Manager.');
    return parts.join('\n');
  }

  private load(id: string): void {
    this.http
      .get<AttributionResponse>(`${environment.apiBaseUrl}/conversations/${id}/attribution`)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (a) => this.attribution.set(a),
        error: (_err: HttpErrorResponse) => {
          // Silent failure — attribution is best-effort UX, not a
          // blocking surface. The chip simply doesn't render.
          this.attribution.set(null);
        },
      });
  }
}

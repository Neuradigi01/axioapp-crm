import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { Router } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

export interface VCardAttachment {
  type: 'contacts';
  formatted_name?: string | null;
  primary_phone?: string | null;
  primary_email?: string | null;
  cards?: Array<Record<string, unknown>>;
}

/**
 * Contact-card bubble (whatsapp-platform-upgrade Step 28).
 *
 * Renders Meta's `contacts` payload as a clickable card with an
 * "Add to contacts" CTA. We don't auto-create the contact — the
 * operator clicks Add → the existing `/user/contacts` create flow
 * opens with the vCard fields pre-filled via query params, so the
 * operator can review (and dedup) before saving.
 *
 * Multi-card payloads are uncommon but supported by Meta — we
 * surface only the primary in the bubble + the rest are still
 * accessible in the raw payload for forensics.
 */
@Component({
  selector: 'app-vcard-bubble',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  template: `
    <div class="rounded-md border border-zinc-200 bg-white p-2">
      <div class="flex items-start gap-2">
        <div
          class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-zinc-600"
        >
          <lucide-icon name="user" class="h-4 w-4" />
        </div>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-medium text-zinc-900">
            {{ vcard().formatted_name || vcard().primary_phone || 'Contact' }}
          </p>
          @if (vcard().primary_phone) {
            <p class="truncate text-xs text-zinc-600">
              {{ vcard().primary_phone }}
            </p>
          }
          @if (vcard().primary_email) {
            <p class="truncate text-xs text-zinc-600">
              {{ vcard().primary_email }}
            </p>
          }
        </div>
      </div>
      <button
        type="button"
        (click)="onAddToContacts()"
        class="mt-2 inline-flex w-full items-center justify-center gap-1 rounded-md border border-zinc-300 bg-zinc-50 px-2.5 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-100"
      >
        <lucide-icon name="user-plus" class="h-3 w-3" />
        Add to contacts
      </button>
    </div>
  `,
})
export class VCardBubbleComponent {
  private readonly router = inject(Router);

  readonly vcard = input.required<VCardAttachment>();

  protected onAddToContacts(): void {
    const card = this.vcard();
    // Open the contacts list with the create modal pre-seeded via
    // query params. The contacts page reads these on mount when the
    // dedup-create modal is wired (Phase 4) and falls back to a
    // plain "navigate to /contacts" otherwise.
    this.router.navigate(['/user/contacts'], {
      queryParams: {
        prefill: '1',
        full_name: card.formatted_name ?? '',
        phone: card.primary_phone ?? '',
        email: card.primary_email ?? '',
        source: 'whatsapp_vcard',
      },
    });
  }
}

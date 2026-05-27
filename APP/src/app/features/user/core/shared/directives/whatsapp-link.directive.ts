import {
  Directive,
  ElementRef,
  Renderer2,
  computed,
  effect,
  inject,
  input,
} from '@angular/core';

/**
 * Wraps a phone string into a `https://wa.me/<digits>` link.
 *
 *   <a [appWhatsappLink]="item.phone">
 *     <lucide-icon name="message-circle" class="h-4 w-4" />
 *   </a>
 *
 * `wa.me` accepts E.164 digits without the leading `+`. We strip every
 * non-digit; if the resulting suffix has no country code (10 digits
 * exactly), default to India (`+91`) which is this product's primary
 * market. Hosts with malformed / too-short input render inert.
 *
 * Always opens in a new tab — WhatsApp's deep link can't replace the
 * current CRM session.
 */
@Directive({
  selector: '[appWhatsappLink]',
  standalone: true,
})
export class WhatsappLinkDirective {
  appWhatsappLink = input<string | null | undefined>(null);

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly renderer = inject(Renderer2);

  private readonly href = computed(() => {
    const raw = (this.appWhatsappLink() ?? '').trim();
    if (!raw) return null;
    let digits = raw.replace(/\D/g, '');
    if (digits.length < 6) return null;
    // Default to India country code for 10-digit local numbers — this
    // CRM ships for Indian furniture retailers.
    if (digits.length === 10) digits = `91${digits}`;
    return `https://wa.me/${digits}`;
  });

  constructor() {
    effect(() => {
      const el = this.host.nativeElement;
      const href = this.href();
      if (href === null) {
        this.renderer.removeAttribute(el, 'href');
        this.renderer.removeAttribute(el, 'role');
        this.renderer.removeAttribute(el, 'target');
        this.renderer.removeAttribute(el, 'rel');
        this.renderer.removeAttribute(el, 'aria-label');
      } else {
        this.renderer.setAttribute(el, 'href', href);
        this.renderer.setAttribute(el, 'role', 'link');
        this.renderer.setAttribute(el, 'target', '_blank');
        this.renderer.setAttribute(el, 'rel', 'noopener noreferrer');
        this.renderer.setAttribute(el, 'aria-label', 'Open in WhatsApp');
      }
    });
  }
}

import { Directive, ElementRef, Renderer2, computed, effect, inject, input } from '@angular/core';

/**
 * Wraps a phone string into a working `tel:` link on the host element.
 *
 * Applied to any `<a>` (or other clickable host):
 *
 *   <a [appPhoneLink]="item.phone">{{ item.phone ?? '—' }}</a>
 *
 * When the input is `null` / empty / too short, the directive removes
 * the `href` + `role` so the host renders inert (no underline, no
 * hover) instead of being a dangling-`tel:` link.
 *
 * Normalisation: strips spaces / dashes / parens so `+91 9000000001`
 * becomes `tel:+919000000001`. Leaves the `+` in place — softphones
 * need it to know it's international.
 */
@Directive({
  selector: '[appPhoneLink]',
  standalone: true,
})
export class PhoneLinkDirective {
  appPhoneLink = input<string | null | undefined>(null);

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly renderer = inject(Renderer2);

  private readonly href = computed(() => {
    const raw = (this.appPhoneLink() ?? '').trim();
    if (!raw) return null;
    // Keep the leading `+`; strip everything else that isn't a digit.
    const cleaned = raw.replace(/[^\d+]/g, '');
    const digitCount = cleaned.replace(/\D/g, '').length;
    if (digitCount < 6) return null;
    return `tel:${cleaned}`;
  });

  constructor() {
    effect(() => {
      const el = this.host.nativeElement;
      const href = this.href();
      if (href === null) {
        this.renderer.removeAttribute(el, 'href');
        this.renderer.removeAttribute(el, 'role');
        this.renderer.removeAttribute(el, 'aria-label');
      } else {
        this.renderer.setAttribute(el, 'href', href);
        this.renderer.setAttribute(el, 'role', 'link');
        this.renderer.setAttribute(el, 'aria-label', `Call ${href.slice(4)}`);
      }
    });
  }
}

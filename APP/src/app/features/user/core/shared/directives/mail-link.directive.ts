import { Directive, ElementRef, Renderer2, computed, effect, inject, input } from '@angular/core';

/**
 * Wraps an email address into a `mailto:` link on the host element.
 *
 *   <a [appMailLink]="item.email">{{ item.email ?? '—' }}</a>
 *
 * `null` / empty / obviously-invalid (missing `@`) inputs render inert.
 * No deep validation — the backend has already EmailStr-validated on
 * create / update.
 */
@Directive({
  selector: '[appMailLink]',
  standalone: true,
})
export class MailLinkDirective {
  appMailLink = input<string | null | undefined>(null);

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly renderer = inject(Renderer2);

  private readonly href = computed(() => {
    const raw = (this.appMailLink() ?? '').trim();
    if (!raw || !raw.includes('@')) return null;
    return `mailto:${raw}`;
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
        this.renderer.setAttribute(el, 'aria-label', `Email ${href.slice(7)}`);
      }
    });
  }
}

import { Directive, ElementRef, Renderer2, computed, effect, inject, input } from '@angular/core';

/**
 * Wraps an email address into a Gmail-compose link that opens in a
 * new tab.
 *
 *   <a [appMailLink]="item.email">
 *     <lucide-icon name="mail" class="h-4 w-4" />
 *   </a>
 *
 * Why not `mailto:` — the OS-default mailto handler is unreliable on
 * Windows without Outlook: clicks silently no-op instead of opening a
 * compose window. Gmail compose in a new tab works for every operator
 * regardless of what desktop client they have installed, and matches
 * the "always open in a new tab" behaviour of `appWhatsappLink`
 * (which uses `https://wa.me/<phone>` for the same portability reason).
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
    // Gmail compose URL — `view=cm` puts it in compose mode, `fs=1`
    // makes it full-screen, `to=<addr>` pre-fills the recipient. Works
    // even when the operator isn't signed in (Gmail prompts for login
    // first, then opens compose).
    return `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(raw)}`;
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
        this.renderer.setAttribute(el, 'aria-label', `Email ${this.appMailLink()}`);
      }
    });
  }
}

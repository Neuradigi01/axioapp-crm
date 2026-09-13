import { Injectable, inject, signal } from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { Title } from '@angular/platform-browser';

import { Brand, DEFAULT_BRAND, resolveBrand } from '@core/constants/brands';

/**
 * Resolves the active brand from the hostname and applies the parts of it the
 * DOM owns — title, favicon and PWA manifest. Components read `brand()` for
 * everything else.
 *
 * `init()` runs in the app initializer, before the first route renders, so no
 * component ever observes the default brand on a branded host.
 *
 * The favicon and manifest `<link>` elements are REWRITTEN rather than added:
 * `index.html` ships the default brand's, so a browser that requests them
 * before Angular boots gets a real file instead of a 404, and a branded host
 * simply repoints them a moment later.
 */
@Injectable({ providedIn: 'root' })
export class BrandService {
  private readonly document = inject(DOCUMENT);
  private readonly title = inject(Title);

  /** The active brand. Safe to read before `init()` — defaults sensibly. */
  readonly brand = signal<Brand>(DEFAULT_BRAND);

  init(): void {
    const brand = resolveBrand(this.document.location.hostname);
    this.brand.set(brand);

    this.title.setTitle(brand.name);
    this.setLinkHref('icon', brand.faviconUrl);
    this.setLinkHref('manifest', brand.manifestUrl);
  }

  /**
   * Point an existing `<link rel="...">` at a new href.
   *
   * Does nothing when the element is absent. That is the correct response
   * rather than creating one: the links are declared in `index.html`, so a
   * missing element means the shell changed, and silently injecting a
   * replacement would hide that from whoever changed it.
   */
  private setLinkHref(rel: string, href: string): void {
    const link = this.document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);
    link?.setAttribute('href', href);
  }
}

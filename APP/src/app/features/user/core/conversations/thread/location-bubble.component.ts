import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, signal } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

export interface LocationAttachment {
  type: 'location';
  latitude: number;
  longitude: number;
  name?: string | null;
  address?: string | null;
}

/**
 * Location bubble (whatsapp-platform-upgrade Step 28).
 *
 * Renders the customer's shared location as a thumbnail card. We
 * deliberately don't call a third-party static-map API on every
 * render (rate limits + DPDP — sharing the customer's coords with
 * Google / Mapbox would need a separate consent surface). Instead
 * we use OpenStreetMap's free Static Map service via a tile-bounds
 * URL that browsers happily render as an `<img>`; falls back to
 * coords-only when the tile load fails.
 *
 * "Open in Maps" deeplinks to the user's preferred map app via the
 * universal `geo:` URI on mobile + a `maps.google.com` web URL on
 * desktop (most browsers also honour `geo:`).
 */
@Component({
  selector: 'app-location-bubble',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  template: `
    <div class="overflow-hidden rounded-md border border-zinc-200 bg-zinc-50">
      <div class="relative">
        <img
          [src]="staticMapUrl()"
          [alt]="'Map showing ' + lat() + ', ' + lng()"
          class="block h-32 w-full object-cover"
          loading="lazy"
          (error)="onTileError($event)"
        />
        @if (tileFailed()) {
          <div
            class="absolute inset-0 flex items-center justify-center bg-zinc-100 text-xs text-zinc-500"
          >
            <lucide-icon name="map-pin" class="mr-1 h-3 w-3" />
            {{ lat().toFixed(4) }}, {{ lng().toFixed(4) }}
          </div>
        }
      </div>
      <div class="px-2 py-1.5 text-xs">
        @if (location().name) {
          <p class="font-semibold text-zinc-800">{{ location().name }}</p>
        }
        @if (location().address) {
          <p class="text-zinc-600">{{ location().address }}</p>
        }
        <a
          [href]="geoUrl()"
          target="_blank"
          rel="noopener noreferrer"
          class="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-sky-700 hover:text-sky-900"
        >
          <lucide-icon name="external-link" class="h-3 w-3" />
          Open in Maps
        </a>
      </div>
    </div>
  `,
})
export class LocationBubbleComponent {
  readonly location = input.required<LocationAttachment>();

  protected readonly tileFailed = signal<boolean>(false);

  protected lat(): number {
    return Number(this.location().latitude) || 0;
  }

  protected lng(): number {
    return Number(this.location().longitude) || 0;
  }

  /** OpenStreetMap static-image via the `staticmap.openstreetmap.de`
   *  endpoint (free, no auth). Generates a 320x140 tile centred on
   *  the coordinates with a single marker. */
  protected staticMapUrl(): string {
    const lat = this.lat();
    const lng = this.lng();
    return (
      `https://staticmap.openstreetmap.de/staticmap.php` +
      `?center=${lat},${lng}` +
      `&zoom=15&size=320x140&maptype=mapnik` +
      `&markers=${lat},${lng},lightblue1`
    );
  }

  protected geoUrl(): string {
    const lat = this.lat();
    const lng = this.lng();
    // `geo:` is honoured by every mobile OS + most desktops; the
    // Google Maps fallback ensures something opens when geo: isn't
    // registered. Most browsers prompt to choose.
    return `https://www.google.com/maps?q=${lat},${lng}`;
  }

  protected onTileError(_event: Event): void {
    this.tileFailed.set(true);
  }
}

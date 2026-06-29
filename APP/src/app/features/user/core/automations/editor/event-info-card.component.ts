import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import type { EventCatalogEntry } from '../automations-api.service';

/**
 * Event-info card — shown under the event picker. Renders the
 * selected event's label + description + a collapsible sample
 * payload viewer so the operator can see which paths are
 * available for the condition builder + the variable picker.
 *
 * Pure presentation; the page owns the catalog + selected event
 * lookup.
 */
@Component({
  selector: 'app-event-info-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './event-info-card.component.html',
})
export class EventInfoCardComponent {
  readonly entry = input<EventCatalogEntry | null>(null);

  protected readonly expanded = signal<boolean>(false);

  protected readonly samplePayloadJson = computed(() => {
    const e = this.entry();
    if (!e) return '';
    try {
      return JSON.stringify(e.sample_payload, null, 2);
    } catch {
      return String(e.sample_payload);
    }
  });

  protected toggleExpanded(): void {
    this.expanded.update((v) => !v);
  }
}

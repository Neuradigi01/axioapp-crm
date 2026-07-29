import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

/**
 * Reusable empty-state card content. Renders a centered icon + headline +
 * optional subline + optional primary CTA (as projected content).
 *
 *   <app-empty-state
 *     icon="inbox"
 *     title="No leads yet."
 *     subtitle="Capture your first one from Google Ads or a landing page.">
 *     <button type="button" class="btn btn-primary">
 *       <lucide-icon name="plus" class="h-4 w-4" />
 *       New lead
 *     </button>
 *   </app-empty-state>
 */
@Component({
  selector: 'app-empty-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './empty-state.component.html',
})
export class EmptyStateComponent {
  /** Lucide icon name — must be registered in app.config.ts. */
  readonly icon = input<string | null>(null);
  /** Main headline (14px 600). */
  readonly title = input.required<string>();
  /** Optional secondary line (13px text-muted). */
  readonly subtitle = input<string | null>(null);
}

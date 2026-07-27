import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Reusable page header — title + optional subtitle on the left, projected
 * action buttons on the right. Sits at the top of every list/detail page.
 *
 *   <app-page-header
 *     title="Contacts"
 *     subtitle="All the people you've added.">
 *     <button type="button" class="btn btn-primary">+ New contact</button>
 *   </app-page-header>
 */
@Component({
  selector: 'app-page-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  templateUrl: './page-header.component.html',
})
export class PageHeaderComponent {
  /** Big display headline. */
  readonly title = input.required<string>();
  /** Optional secondary line beneath the title. */
  readonly subtitle = input<string | null>(null);
}

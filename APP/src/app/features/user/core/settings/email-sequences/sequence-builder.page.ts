/**
 * Route shell for `/user/settings/email-sequences/new` and
 * `/.../:id/edit`. Reads the `:id` param off the route and hands it
 * to the builder as a typed input. `/new` resolves to a null id which
 * the builder renders as a create form.
 */
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { SequenceBuilderComponent } from './sequence-builder.component';


@Component({
  selector: 'app-sequence-builder-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SequenceBuilderComponent],
  template: `<app-sequence-builder [sequenceId]="sequenceId()" />`,
})
export class SequenceBuilderPageComponent {
  private readonly route = inject(ActivatedRoute);

  readonly sequenceId = computed<string | null>(() => {
    return this.route.snapshot.paramMap.get('id') ?? null;
  });
}

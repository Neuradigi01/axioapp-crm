/**
 * Route shell for `/user/settings/email-templates/new` and
 * `/.../:id/edit`. Reads the `:id` param off the route and hands it
 * to the editor component as a typed input. `/new` resolves to a
 * null id which the editor renders as a create form.
 */
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { EmailTemplateEditorComponent } from './template-editor.component';


@Component({
  selector: 'app-email-template-editor-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [EmailTemplateEditorComponent],
  template: `
    <app-email-template-editor [templateId]="templateId()" />
  `,
})
export class EmailTemplateEditorPageComponent {
  private readonly route = inject(ActivatedRoute);

  readonly templateId = computed<string | null>(() => {
    return this.route.snapshot.paramMap.get('id') ?? null;
  });
}

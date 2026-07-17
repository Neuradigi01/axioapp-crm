import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { HtmlComposerComponent } from './html-composer.component';

/**
 * Email sub-form — subject + preview text + plain body + HTML body.
 *
 * Campaigns v1 Step 04 — the plain-body textarea now sits alongside a
 * dedicated HTML composer (source + live preview). The operator can
 * fill either or both; if they leave ``body_text`` empty AND enable
 * ``body_text_fallback_auto`` (default true), the backend derives the
 * plain-text fallback from the sanitised HTML on save. Variable
 * picker is rendered by the parent editor for the plain body; the
 * HTML composer has its own inline merge-tag inserter.
 */
export type EmailFormGroup = FormGroup<{
  subject: FormControl<string>;
  preview_text: FormControl<string>;
  body_text: FormControl<string>;
  body_html: FormControl<string>;
  body_text_fallback_auto: FormControl<boolean>;
}>;

@Component({
  selector: 'app-email-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, HtmlComposerComponent],
  templateUrl: './email-form.component.html',
})
export class EmailFormComponent {
  readonly form = input.required<EmailFormGroup>();
  readonly disabled = input<boolean>(false);
  /** Called by the parent editor's `(focus)` handlers to track which
   *  textarea is active so the variable picker knows where to insert. */
  readonly trackFocus = input<(el: HTMLTextAreaElement | HTMLInputElement) => void>(
    () => undefined,
  );

  protected onFocus(event: FocusEvent): void {
    const el = event.target as HTMLTextAreaElement | HTMLInputElement;
    this.trackFocus()(el);
  }

  protected onHtmlChange(html: string): void {
    this.form().controls.body_html.setValue(html);
    this.form().controls.body_html.markAsDirty();
  }

  static build(): EmailFormGroup {
    return new FormGroup({
      subject: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.required, Validators.maxLength(998)],
      }),
      preview_text: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.maxLength(190)],
      }),
      // Not required at the form level any more — the backend accepts
      // Email templates with only body_html, and derives body_text
      // automatically when the fallback flag is on. The parent editor
      // guards "at least one of body_text / body_html" before submit.
      body_text: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.maxLength(65535)],
      }),
      // Campaigns v1 Step 04 — HTML source. Sanitised server-side.
      body_html: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.maxLength(200000)],
      }),
      body_text_fallback_auto: new FormControl<boolean>(true, {
        nonNullable: true,
      }),
    });
  }
}

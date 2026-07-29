import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import {
  AbstractControl,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';

import { commonValidators } from '../../shared/validators';
import { HtmlComposerComponent } from './html-composer.component';

/**
 * Group-level guard: the backend accepts either `body_text` OR `body_html`
 * (auto-derives the missing side per `body_text_fallback_auto`) but at
 * least one must be non-empty. Mirrored client-side so the submit
 * button reflects the real state instead of failing on POST.
 */
function emailBodyPresenceValidator(group: AbstractControl): ValidationErrors | null {
  const text = String(group.get('body_text')?.value ?? '').trim();
  const html = String(group.get('body_html')?.value ?? '').trim();
  return text.length === 0 && html.length === 0 ? { bodyMissing: true } : null;
}

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
    return new FormGroup(
      {
        subject: new FormControl<string>('', {
          nonNullable: true,
          validators: [commonValidators.trimmedRequired, Validators.maxLength(998)],
        }),
        preview_text: new FormControl<string>('', {
          nonNullable: true,
          validators: [Validators.maxLength(190)],
        }),
        // Not required at the control level — either body_text OR body_html
        // is acceptable. The group-level `emailBodyPresenceValidator` enforces
        // "at least one non-empty" so the submit button reflects reality.
        body_text: new FormControl<string>('', {
          nonNullable: true,
          validators: [Validators.maxLength(65535)],
        }),
        // Campaigns v1 Step 04 — HTML source. Sanitised server-side. Cap
        // matches common ESP limits (100 KB) — bigger templates are
        // essentially always a copy-paste accident.
        body_html: new FormControl<string>('', {
          nonNullable: true,
          validators: [Validators.maxLength(100000)],
        }),
        body_text_fallback_auto: new FormControl<boolean>(true, {
          nonNullable: true,
        }),
      },
      { validators: [emailBodyPresenceValidator] },
    );
  }
}

import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

/**
 * Email sub-form — subject + preview text + plain body.
 *
 * Visual / drag-drop editor is out of scope for v1; the body is a
 * plain textarea where the operator can paste HTML or write text.
 * The preview pane renders it as-is. Variable picker is rendered
 * by the parent editor (sub-form just provides the textareas).
 */
export type EmailFormGroup = FormGroup<{
  subject: FormControl<string>;
  preview_text: FormControl<string>;
  body_text: FormControl<string>;
}>;

@Component({
  selector: 'app-email-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
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
      body_text: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.required, Validators.maxLength(65535)],
      }),
    });
  }
}

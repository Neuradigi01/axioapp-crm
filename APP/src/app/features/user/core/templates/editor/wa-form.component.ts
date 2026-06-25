import {
  ChangeDetectionStrategy,
  Component,
  input,
} from '@angular/core';
import {
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';

/**
 * WhatsApp sub-form — channel-agnostic fields only (body + language).
 *
 * The Meta-specific extras (header type / button payloads / template
 * category) live in the WA-specific extension table from Step 9.
 * Until then this sub-form ships the minimal field set that the
 * central `tbl_message_templates` already supports — name, body,
 * language. The operator can still create + edit a WA template; Step 9
 * adds the header / buttons UI alongside the Meta-submission flow.
 */
export type WaFormGroup = FormGroup<{
  body_text: FormControl<string>;
  language: FormControl<string>;
}>;


const LANGUAGE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'en', label: 'English (en)' },
  { value: 'hi', label: 'Hindi (hi)' },
  { value: 'mr', label: 'Marathi (mr)' },
  { value: 'gu', label: 'Gujarati (gu)' },
  { value: 'ta', label: 'Tamil (ta)' },
  { value: 'te', label: 'Telugu (te)' },
  { value: 'kn', label: 'Kannada (kn)' },
  { value: 'ml', label: 'Malayalam (ml)' },
  { value: 'pa', label: 'Punjabi (pa)' },
  { value: 'bn', label: 'Bengali (bn)' },
];


@Component({
  selector: 'app-wa-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './wa-form.component.html',
})
export class WaFormComponent {
  readonly form = input.required<WaFormGroup>();
  readonly disabled = input<boolean>(false);
  readonly trackFocus = input<(el: HTMLTextAreaElement | HTMLInputElement) => void>(
    () => undefined,
  );

  protected readonly LANGUAGE_OPTIONS = LANGUAGE_OPTIONS;

  protected onFocus(event: FocusEvent): void {
    const el = event.target as HTMLTextAreaElement | HTMLInputElement;
    this.trackFocus()(el);
  }

  static build(): WaFormGroup {
    return new FormGroup({
      body_text: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.required, Validators.maxLength(1024)],
      }),
      language: new FormControl<string>('en', {
        nonNullable: true,
        validators: [Validators.required],
      }),
    });
  }
}

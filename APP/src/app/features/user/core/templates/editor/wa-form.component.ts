import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { FormArray, FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { LucideAngularModule } from 'lucide-angular';
import { commonValidators } from '../../shared/validators';

/**
 * WhatsApp sub-form — full Meta-template shape.
 *
 * Covers the fields Meta's ``/{waba_id}/message_templates`` endpoint
 * accepts:
 *
 *  - ``category``      — Marketing / Utility / Authentication.
 *                        Rendered as three visual cards; required.
 *  - ``header_type``   — text (default) / image / video / document.
 *                        Media headers are declared here but the
 *                        actual sample media upload still happens on
 *                        the separate Meta-submission page.
 *  - ``header_text``   — text-only header string (max 60 chars).
 *  - ``body_text``     — the message body, up to 1024 chars.
 *  - ``footer_text``   — optional single-line footer (max 60 chars).
 *  - ``buttons``       — up to 3 CTAs. Each button is either URL,
 *                        Phone, or Quick Reply; the type dictates the
 *                        required companion field.
 *
 * The parent template-editor page maps this form into a
 * ``whatsapp`` sub-payload on ``TemplateCreate`` / ``TemplateUpdate``;
 * the backend upserts the ``tbl_whatsapp_templates`` extension row so
 * the Submit-to-Meta flow can send the payload verbatim.
 */
export type WaButtonType = 'url' | 'phone_number' | 'quick_reply';
export type WaCategory = 'marketing' | 'utility' | 'authentication';
export type WaHeaderType = '' | 'text' | 'image' | 'video' | 'document';

export type WaButtonFormGroup = FormGroup<{
  type: FormControl<WaButtonType>;
  text: FormControl<string>;
  url: FormControl<string>;
  phone_number: FormControl<string>;
}>;

export type WaFormGroup = FormGroup<{
  body_text: FormControl<string>;
  language: FormControl<string>;
  category: FormControl<WaCategory>;
  header_type: FormControl<WaHeaderType>;
  header_text: FormControl<string>;
  footer_text: FormControl<string>;
  buttons: FormArray<WaButtonFormGroup>;
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

const CATEGORY_OPTIONS: Array<{ value: WaCategory; label: string; blurb: string }> = [
  {
    value: 'marketing',
    label: 'Marketing',
    blurb: 'Promotions, offers, launches, newsletters.',
  },
  {
    value: 'utility',
    label: 'Utility',
    blurb: 'Order updates, appointment reminders, account alerts.',
  },
  {
    value: 'authentication',
    label: 'Authentication',
    blurb: 'One-time passwords + verification codes.',
  },
];

@Component({
  selector: 'app-wa-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule],
  templateUrl: './wa-form.component.html',
})
export class WaFormComponent {
  readonly form = input.required<WaFormGroup>();
  readonly disabled = input<boolean>(false);
  readonly trackFocus = input<(el: HTMLTextAreaElement | HTMLInputElement) => void>(
    () => undefined,
  );

  protected readonly LANGUAGE_OPTIONS = LANGUAGE_OPTIONS;
  protected readonly CATEGORY_OPTIONS = CATEGORY_OPTIONS;

  /** Meta caps at 3 buttons per template. Disables the Add button
   *  when the array is full so the operator can't build an invalid
   *  template on the client. */
  protected readonly canAddButton = computed<boolean>(
    () => this.form().controls.buttons.length < 3,
  );

  protected onFocus(event: FocusEvent): void {
    const el = event.target as HTMLTextAreaElement | HTMLInputElement;
    this.trackFocus()(el);
  }

  protected pickCategory(cat: WaCategory): void {
    if (this.disabled()) return;
    this.form().controls.category.setValue(cat);
  }

  protected addButton(type: WaButtonType = 'url'): void {
    if (this.disabled() || !this.canAddButton()) return;
    const group = WaFormComponent.buildButton({ type });
    WaFormComponent.wireSiblingClear(group);
    this.form().controls.buttons.push(group);
  }

  protected removeButton(index: number): void {
    if (this.disabled()) return;
    this.form().controls.buttons.removeAt(index);
  }

  /** Static wiring — clears whichever sibling field doesn't belong
   *  to the active button type. The subscription is not tied to any
   *  component's lifecycle; instead we rely on the parent FormGroup /
   *  FormArray being GC'd when the page destroys, which detaches every
   *  observer on its controls automatically. Called from both
   *  ``addButton`` (new-add) and the parent template-editor's hydrate
   *  path (loaded from server). */
  static wireSiblingClear(group: WaButtonFormGroup): void {
    group.controls.type.valueChanges.subscribe((newType) => {
      if (newType === 'url') {
        group.controls.phone_number.setValue('', { emitEvent: false });
      } else if (newType === 'phone_number') {
        group.controls.url.setValue('', { emitEvent: false });
      } else {
        group.controls.url.setValue('', { emitEvent: false });
        group.controls.phone_number.setValue('', { emitEvent: false });
      }
    });
  }

  static buildButton(init?: {
    type?: WaButtonType;
    text?: string;
    url?: string;
    phone_number?: string;
  }): WaButtonFormGroup {
    return new FormGroup({
      type: new FormControl<WaButtonType>(init?.type ?? 'url', { nonNullable: true }),
      text: new FormControl<string>(init?.text ?? '', {
        nonNullable: true,
        validators: [Validators.required, Validators.maxLength(25)],
      }),
      url: new FormControl<string>(init?.url ?? '', {
        nonNullable: true,
        validators: [Validators.maxLength(2000)],
      }),
      phone_number: new FormControl<string>(init?.phone_number ?? '', {
        nonNullable: true,
        validators: [Validators.maxLength(32)],
      }),
    });
  }

  static build(): WaFormGroup {
    return new FormGroup({
      body_text: new FormControl<string>('', {
        nonNullable: true,
        validators: [
          commonValidators.trimmedRequired,
          Validators.maxLength(1024),
          commonValidators.waVariables,
        ],
      }),
      language: new FormControl<string>('en', {
        nonNullable: true,
        validators: [Validators.required],
      }),
      category: new FormControl<WaCategory>('marketing', {
        nonNullable: true,
        validators: [
          Validators.required,
          commonValidators.picklist(['marketing', 'utility', 'authentication']),
        ],
      }),
      header_type: new FormControl<WaHeaderType>('', {
        nonNullable: true,
        validators: [commonValidators.picklist(['', 'text', 'image', 'video', 'document'])],
      }),
      header_text: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.maxLength(60), commonValidators.waVariables],
      }),
      footer_text: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.maxLength(60)],
      }),
      buttons: new FormArray<WaButtonFormGroup>([]),
    });
  }
}

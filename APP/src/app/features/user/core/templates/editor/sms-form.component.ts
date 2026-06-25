import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';

/**
 * SMS sub-form for the central template editor (Step 12).
 *
 * Captures:
 *   - body (TRAI-flagged for content; max 160 chars per segment)
 *   - DLT entity ID (operator's Principal Entity id)
 *   - DLT template ID (TRAI-issued; entered after the operator
 *     finishes registration on the DLT portal)
 *   - DLT content category (TRAI's 4-way classification —
 *     distinct from our internal marketing/transactional flag)
 *   - DLT header (6-char alphanumeric sender id)
 *   - DLT principal entity id (telco-quirky; sometimes distinct
 *     from entity_id)
 *
 * The DLT-portal submission stays out-of-CRM (TRAI requires
 * external portals). After registration the operator pastes the
 * approved ids into this form; the future SMS-provider adapter
 * uses them at send time.
 *
 * Char counter math: 160 chars / segment (GSM-7); shown beneath the
 * textarea so the operator knows when a long body fans out across
 * multiple SMS units. Encoding-aware count (UCS-2 = 70 chars when
 * any Unicode codepoint is present) is a polish step deferred.
 */
export type SmsFormGroup = FormGroup<{
  body_text: FormControl<string>;
  dlt_entity_id: FormControl<string>;
  dlt_template_id: FormControl<string>;
  dlt_content_category: FormControl<
    'transactional' | 'promotional' | 'service_explicit' | 'service_implicit'
  >;
  dlt_header: FormControl<string>;
  dlt_principal_entity_id: FormControl<string>;
  dlt_template_status: FormControl<'registered' | 'pending' | 'rejected'>;
}>;


const CONTENT_CATEGORY_OPTIONS: Array<{
  value: SmsFormGroup['controls']['dlt_content_category']['value'];
  label: string;
  description: string;
}> = [
  {
    value: 'transactional',
    label: 'Transactional',
    description: 'OTPs, order updates, invoice receipts',
  },
  {
    value: 'promotional',
    label: 'Promotional',
    description: 'Marketing offers, broadcasts',
  },
  {
    value: 'service_explicit',
    label: 'Service (explicit)',
    description: 'Customer opted into service messages',
  },
  {
    value: 'service_implicit',
    label: 'Service (implicit)',
    description: 'Messages tied to an existing transaction',
  },
];


const STATUS_OPTIONS: Array<{
  value: SmsFormGroup['controls']['dlt_template_status']['value'];
  label: string;
}> = [
  { value: 'pending', label: 'Pending DLT review' },
  { value: 'registered', label: 'Registered (live)' },
  { value: 'rejected', label: 'Rejected by DLT' },
];


@Component({
  selector: 'app-sms-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './sms-form.component.html',
})
export class SmsFormComponent {
  private readonly destroyRef = inject(DestroyRef);

  readonly form = input.required<SmsFormGroup>();
  readonly disabled = input<boolean>(false);
  readonly trackFocus = input<(el: HTMLTextAreaElement | HTMLInputElement) => void>(
    () => undefined,
  );

  protected readonly CONTENT_CATEGORY_OPTIONS = CONTENT_CATEGORY_OPTIONS;
  protected readonly STATUS_OPTIONS = STATUS_OPTIONS;

  // FormControl values are not signal-backed, so mirror the two
  // fields that drive the char counter + category-help text into
  // signals via valueChanges. Re-subscribed when the parent swaps
  // the form input (rare, but possible on draft → /:id navigation).
  private readonly bodyText = signal<string>('');
  private readonly contentCategory = signal<
    SmsFormGroup['controls']['dlt_content_category']['value']
  >('transactional');

  constructor() {
    effect((onCleanup) => {
      const f = this.form();
      this.bodyText.set(f.controls.body_text.value);
      this.contentCategory.set(f.controls.dlt_content_category.value);
      const subBody = f.controls.body_text.valueChanges
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((v) => this.bodyText.set(v ?? ''));
      const subCat = f.controls.dlt_content_category.valueChanges
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((v) => this.contentCategory.set(v));
      onCleanup(() => {
        subBody.unsubscribe();
        subCat.unsubscribe();
      });
    });
  }

  protected readonly bodyLength = computed(() => this.bodyText().length);
  protected readonly selectedCategoryDescription = computed(() => {
    const v = this.contentCategory();
    return (
      CONTENT_CATEGORY_OPTIONS.find((o) => o.value === v)?.description ?? ''
    );
  });
  /** TRAI-aware segment count: 160-char chunks for GSM-7. Anything
   *  past the first 160 splits at 153 (each header eats 7 bytes),
   *  but the simplified counter just divides ceiling by 160 — good
   *  enough for v1 + visible to the operator. */
  protected readonly segmentCount = computed(() => {
    const len = this.bodyLength();
    if (len === 0) return 0;
    if (len <= 160) return 1;
    return Math.ceil((len - 160) / 153) + 1;
  });

  protected onFocus(event: FocusEvent): void {
    const el = event.target as HTMLTextAreaElement | HTMLInputElement;
    this.trackFocus()(el);
  }

  protected onHeaderInput(value: string): void {
    // Header is 6-char uppercase alphanumeric per TRAI spec.
    const normalised = value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6);
    if (this.form().controls.dlt_header.value !== normalised) {
      this.form().controls.dlt_header.setValue(normalised);
    }
  }

  static build(): SmsFormGroup {
    return new FormGroup({
      body_text: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.required, Validators.maxLength(1530)],
      }),
      dlt_entity_id: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.maxLength(128)],
      }),
      dlt_template_id: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.maxLength(128)],
      }),
      dlt_content_category: new FormControl<
        SmsFormGroup['controls']['dlt_content_category']['value']
      >('transactional', { nonNullable: true }),
      dlt_header: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.maxLength(6)],
      }),
      dlt_principal_entity_id: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.maxLength(128)],
      }),
      dlt_template_status: new FormControl<
        SmsFormGroup['controls']['dlt_template_status']['value']
      >('pending', { nonNullable: true }),
    });
  }
}

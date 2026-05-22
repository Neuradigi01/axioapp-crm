import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  OnDestroy,
  OnInit,
  Output,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  FormArray,
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  ValidatorFn,
  Validators,
} from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { Observable, Subject, of } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';
import { extractApiError } from '@core/services/api-error.util';
import { nullableTrim } from '@core/services/form.util';

import {
  ContactListItem,
  ContactsApiService,
} from '../../../core/contacts/contacts-api.service';
import { StandardFieldsApiService } from '../../../core/standard-fields/standard-fields-api.service';
import { StandardFieldsSignalsService } from '../../../core/standard-fields/standard-fields-signals.service';
import type { StandardFieldRendered } from '../../../core/standard-fields/types';
import {
  CustomOrderCreate,
  CustomOrdersApiService,
} from './custom-orders-api.service';

/**
 * Multi-step "New Custom Order" wizard.
 *
 *   1. Basics       â€” contact picker + title + materials/color/finish +
 *                     total / advance / expected delivery date.
 *   2. Measurements â€” repeatable rows (label + L/W/H + notes).
 *   3. Photos       â€” multi-file picker with thumbnail previews.
 *   4. Review       â€” summary + Submit.
 *
 * Submission order: create the order first; then in parallel POST each
 * measurement and upload each photo. We capture per-row errors and
 * still close the modal on success (the parent reloads the list).
 *
 * Object URLs for previews are revoked in `ngOnDestroy` to avoid
 * leaks if the user closes the modal mid-flow.
 */
type PhotoStaged = {
  file: File;
  previewUrl: string;
  caption: string;
};

@Component({
  selector: 'app-custom-order-form-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule],
  templateUrl: './custom-order-form-modal.component.html',
})
export class CustomOrderFormModalComponent implements OnInit, OnDestroy {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(CustomOrdersApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly stdApi = inject(StandardFieldsApiService);
  private readonly stdSignals = inject(StandardFieldsSignalsService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly stdFields = signal<Record<string, StandardFieldRendered>>(
    {},
  );

  protected stdField(key: string): StandardFieldRendered | undefined {
    return this.stdFields()[key];
  }

  protected isHidden(key: string): boolean {
    return this.stdField(key)?.is_hidden === true;
  }

  constructor() {
    effect(() => {
      this.stdSignals.changedAt();
      this.refreshStdFields();
    });
  }

  private refreshStdFields(): void {
    this.stdApi.render('custom_order').subscribe({
      next: (resp) => {
        const map: Record<string, StandardFieldRendered> = {};
        for (const f of resp.items) map[f.field_key] = f;
        this.stdFields.set(map);
        this.applyStandardValidators(map);
      },
      error: () => {
        /* fallbacks keep the form usable */
      },
    });
  }

  /** Layer override-driven validators on top of the static shape validators.
   *  `title` is backend-locked-required. The rest accept `required`; currency
   *  fields additionally accept `min`/`max`. */
  private applyStandardValidators(
    map: Record<string, StandardFieldRendered>,
  ): void {
    this.basics.controls.title.setValidators([
      Validators.required,
      Validators.maxLength(255),
    ]);
    this.basics.controls.title.updateValueAndValidity({ emitEvent: false });

    const setReq = (
      ctrl:
        | 'requirement'
        | 'material_primary'
        | 'material_secondary'
        | 'color'
        | 'finish'
        | 'expected_delivery_date',
      row: StandardFieldRendered | undefined,
    ): void => {
      const v: ValidatorFn[] = [];
      if (row?.is_required) v.push(Validators.required);
      this.basics.controls[ctrl].setValidators(v);
      this.basics.controls[ctrl].updateValueAndValidity({ emitEvent: false });
    };
    setReq('requirement', map['requirement']);
    setReq('material_primary', map['material_primary']);
    setReq('material_secondary', map['material_secondary']);
    setReq('color', map['color']);
    setReq('finish', map['finish']);
    setReq('expected_delivery_date', map['expected_delivery_date']);

    const currencyValidators = (
      row: StandardFieldRendered | undefined,
    ): ValidatorFn[] => {
      const v: ValidatorFn[] = [];
      if (row?.is_required) v.push(Validators.required);
      if (row?.min_value != null) v.push(Validators.min(row.min_value));
      if (row?.max_value != null) v.push(Validators.max(row.max_value));
      return v;
    };
    this.basics.controls.total_amount.setValidators(
      currencyValidators(map['total_amount']),
    );
    this.basics.controls.total_amount.updateValueAndValidity({
      emitEvent: false,
    });
    this.basics.controls.advance_paid.setValidators(
      currencyValidators(map['advance_paid']),
    );
    this.basics.controls.advance_paid.updateValueAndValidity({
      emitEvent: false,
    });
  }

  @Input() set submitting(value: boolean) {
    this._submitting.set(value);
  }

  @Output() readonly created = new EventEmitter<void>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly step = signal<1 | 2 | 3 | 4>(1);
  protected readonly _submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  // Step 1 â€” basics
  readonly basics = this.fb.group({
    title: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    requirement: this.fb.control<string>('', { nonNullable: true }),
    material_primary: this.fb.control<string>('', { nonNullable: true }),
    material_secondary: this.fb.control<string>('', { nonNullable: true }),
    color: this.fb.control<string>('', { nonNullable: true }),
    finish: this.fb.control<string>('', { nonNullable: true }),
    total_amount: this.fb.control<string>('', { nonNullable: true }),
    advance_paid: this.fb.control<string>('', { nonNullable: true }),
    expected_delivery_date: this.fb.control<string>('', { nonNullable: true }),
  });

  // Step 2 â€” measurements (FormArray of FormGroups)
  readonly measurements: FormArray<FormGroup<MeasurementRowGroup>> =
    this.fb.array<FormGroup<MeasurementRowGroup>>([]);

  // Step 3 â€” photos (signal, not a form control â€” File objects are out-of-band)
  protected readonly photos = signal<PhotoStaged[]>([]);

  // Contact picker state
  protected readonly selectedContact = signal<ContactListItem | null>(null);
  protected readonly contactQuery = signal('');
  protected readonly contactResults = signal<ContactListItem[]>([]);
  protected readonly contactSearchOpen = signal(false);
  private readonly contactQuery$ = new Subject<string>();

  protected readonly canAdvance = computed(() => {
    if (this.step() === 1) {
      return this.basics.controls.title.value.trim().length > 0;
    }
    if (this.step() === 2) {
      return this.measurements.controls.every((g) => g.valid);
    }
    return true;
  });

  ngOnInit(): void {
    this.contactQuery$
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        switchMap((q) =>
          this.contactsApi
            .list({ q: q || undefined, size: 8 })
            .pipe(catchError(() => of({ items: [] as ContactListItem[], total: 0, page: 1, size: 8 }))),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((resp) => this.contactResults.set(resp.items));

    // Pre-seed one empty measurement row so the user sees the shape.
    this.addMeasurement();
  }

  ngOnDestroy(): void {
    for (const p of this.photos()) URL.revokeObjectURL(p.previewUrl);
  }

  // --- contact picker ---------------------------------------------------

  protected onContactQueryInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.contactQuery.set(value);
    this.contactSearchOpen.set(true);
    this.contactQuery$.next(value);
  }

  protected selectContact(c: ContactListItem): void {
    this.selectedContact.set(c);
    this.contactSearchOpen.set(false);
    this.contactQuery.set('');
    this.contactResults.set([]);
  }

  protected clearContact(): void {
    this.selectedContact.set(null);
    this.contactQuery.set('');
    this.contactSearchOpen.set(true);
  }

  // --- measurements -----------------------------------------------------

  protected addMeasurement(): void {
    this.measurements.push(
      this.fb.group<MeasurementRowGroup>({
        item_label: this.fb.control<string>('', {
          nonNullable: true,
          validators: [Validators.required, Validators.maxLength(128)],
        }),
        length_cm: this.fb.control<string>('', { nonNullable: true }),
        width_cm: this.fb.control<string>('', { nonNullable: true }),
        height_cm: this.fb.control<string>('', { nonNullable: true }),
        notes: this.fb.control<string>('', { nonNullable: true }),
      }),
    );
  }

  protected removeMeasurement(i: number): void {
    if (this.measurements.length > 1) this.measurements.removeAt(i);
    else this.measurements.at(i).reset();
  }

  // --- photos -----------------------------------------------------------

  protected onPhotoFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = input.files;
    if (!files || files.length === 0) return;
    const staged = [...this.photos()];
    for (let i = 0; i < files.length; i++) {
      const file = files.item(i);
      if (!file) continue;
      staged.push({
        file,
        previewUrl: URL.createObjectURL(file),
        caption: '',
      });
    }
    this.photos.set(staged);
    input.value = '';
  }

  protected removePhoto(i: number): void {
    const list = [...this.photos()];
    const removed = list.splice(i, 1)[0];
    if (removed) URL.revokeObjectURL(removed.previewUrl);
    this.photos.set(list);
  }

  protected updatePhotoCaption(i: number, value: string): void {
    const list = [...this.photos()];
    if (list[i]) list[i] = { ...list[i], caption: value };
    this.photos.set(list);
  }

  // --- step navigation --------------------------------------------------

  protected next(): void {
    if (this.step() === 1) {
      this.basics.controls.title.markAsTouched();
      if (!this.canAdvance()) return;
      this.step.set(2);
    } else if (this.step() === 2) {
      this.measurements.markAllAsTouched();
      if (!this.canAdvance()) return;
      this.step.set(3);
    } else if (this.step() === 3) {
      this.step.set(4);
    }
  }

  protected back(): void {
    if (this.step() === 2) this.step.set(1);
    else if (this.step() === 3) this.step.set(2);
    else if (this.step() === 4) this.step.set(3);
  }

  // --- submit -----------------------------------------------------------

  protected submit(): void {
    if (!this.canAdvance() || this._submitting()) return;
    this._submitting.set(true);
    this.submitError.set(null);

    const v = this.basics.getRawValue();
    const materials: Record<string, string> = {};
    if (v.material_primary.trim()) materials['primary'] = v.material_primary.trim();
    if (v.material_secondary.trim())
      materials['secondary'] = v.material_secondary.trim();

    const payload: CustomOrderCreate = {
      contact_id: this.selectedContact()?.id ?? null,
      title: v.title.trim(),
      requirement: nullableTrim(v.requirement),
      materials,
      color: nullableTrim(v.color),
      finish: nullableTrim(v.finish),
      total_amount: v.total_amount.trim() || '0',
      advance_paid: v.advance_paid.trim() || '0',
      expected_delivery_date: nullableTrim(v.expected_delivery_date),
    };

    this.api
      .create(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (order) => {
          this.persistChildren(order.id);
        },
        error: (err: HttpErrorResponse) => {
          this._submitting.set(false);
          this.submitError.set(
            extractApiError(err) ?? 'Could not create custom order.',
          );
        },
      });
  }

  private persistChildren(orderId: string): void {
    const measurementRequests = this.measurements.controls
      .map((g) => g.getRawValue())
      .filter((row) => row.item_label.trim().length > 0)
      .map((row) =>
        this.api.addMeasurement(orderId, {
          item_label: row.item_label.trim(),
          length_cm: nullableTrim(row.length_cm),
          width_cm: nullableTrim(row.width_cm),
          height_cm: nullableTrim(row.height_cm),
          notes: nullableTrim(row.notes),
        }),
      );

    const photoRequests = this.photos().map((p) =>
      this.api.uploadPhoto(orderId, p.file, p.caption.trim() || null),
    );

    const all: Observable<unknown>[] = [
      ...measurementRequests,
      ...photoRequests,
    ];
    if (all.length === 0) {
      this._submitting.set(false);
      this.created.emit();
      return;
    }

    let remaining = all.length;
    let firstError: string | null = null;
    const done = (): void => {
      remaining -= 1;
      if (remaining === 0) {
        this._submitting.set(false);
        if (firstError) this.submitError.set(firstError);
        this.created.emit();
      }
    };

    for (const req of all) {
      req
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: () => done(),
          error: (err: HttpErrorResponse) => {
            if (!firstError) {
              firstError =
                extractApiError(err)
                ?? 'Order created, but some attachments failed to upload.';
            }
            done();
          },
        });
    }
  }


}

interface MeasurementRowGroup {
  item_label: FormControl<string>;
  length_cm: FormControl<string>;
  width_cm: FormControl<string>;
  height_cm: FormControl<string>;
  notes: FormControl<string>;
}

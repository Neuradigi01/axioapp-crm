import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { MatSnackBar } from '@angular/material/snack-bar';

import { extractApiError } from '@core/services/api-error.util';

import { AmenitiesInputComponent } from './amenities-input.component';
import { PropertyApiService } from './property-api.service';
import { PropertyGalleryComponent } from './property-gallery.component';
import { PropertyRowMenuComponent } from './property-row-menu.component';
import {
  AREA_UNIT_OPTIONS,
  PROPERTY_CATEGORY_OPTIONS,
  PROPERTY_TYPE_OPTIONS,
  type Property,
  type PropertyCategoryKey,
  type PropertyCreate,
  type PropertyImage,
  type PropertyTypeKey,
  type PropertyUpdate,
} from './property.types';

/**
 * Property create / edit form.
 *
 * Route: `/user/properties/new` for create, `/user/properties/:id/edit`
 * for edit. Detected from `route.params`. In edit mode the form
 * hydrates from `PropertyApiService.getById(id)` on init; on submit
 * it round-trips through create (POST → navigate to edit with the
 * new id so the gallery becomes active) or update (PATCH → toast).
 *
 * Sections are laid out as stacked cards (basics, location, details,
 * contact, images). The gallery card is disabled with an inline
 * message in create mode — no property row yet means the upload
 * endpoint has nothing to hang images off.
 */
interface PropertyFormControls {
  title: FormControl<string>;
  property_type: FormControl<PropertyTypeKey | ''>;
  category: FormControl<PropertyCategoryKey | ''>;
  description: FormControl<string>;
  price: FormControl<number | null>;
  currency: FormControl<string>;
  address_line: FormControl<string>;
  city: FormControl<string>;
  state: FormControl<string>;
  country: FormControl<string>;
  pincode: FormControl<string>;
  bedrooms: FormControl<number | null>;
  bathrooms: FormControl<number | null>;
  area_value: FormControl<number | null>;
  area_unit: FormControl<string>;
  amenities: FormControl<string[]>;
  contact_person: FormControl<string>;
  contact_phone: FormControl<string>;
  contact_email: FormControl<string>;
}

@Component({
  selector: 'app-property-form-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    LucideAngularModule,
    RouterLink,
    AmenitiesInputComponent,
    PropertyGalleryComponent,
    PropertyRowMenuComponent,
  ],
  templateUrl: './property-form.page.html',
})
export class PropertyFormPageComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(PropertyApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly TYPE_OPTIONS = PROPERTY_TYPE_OPTIONS;
  protected readonly CATEGORY_OPTIONS = PROPERTY_CATEGORY_OPTIONS;
  protected readonly UNIT_OPTIONS = AREA_UNIT_OPTIONS;

  protected readonly propertyId = signal<string | null>(null);
  protected readonly loading = signal(false);
  protected readonly saving = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly submitError = signal<string | null>(null);
  protected readonly initialImages = signal<PropertyImage[]>([]);
  /** Loaded property row — powers the sticky-footer action menu. Null
   * in create mode until the first save gives us an id. */
  protected readonly currentProperty = signal<Property | null>(null);

  protected readonly isEdit = computed(() => this.propertyId() !== null);
  protected readonly title = computed(() => (this.isEdit() ? 'Edit Property' : 'New Property'));

  protected readonly form: FormGroup<PropertyFormControls> = this.fb.group({
    title: this.fb.nonNullable.control('', [Validators.required, Validators.maxLength(200)]),
    property_type: this.fb.nonNullable.control<PropertyTypeKey | ''>('', [Validators.required]),
    category: this.fb.nonNullable.control<PropertyCategoryKey | ''>('', [Validators.required]),
    description: this.fb.nonNullable.control(''),
    price: this.fb.control<number | null>(null),
    currency: this.fb.nonNullable.control('INR', [Validators.maxLength(3)]),
    address_line: this.fb.nonNullable.control('', [Validators.maxLength(500)]),
    city: this.fb.nonNullable.control('', [Validators.maxLength(100)]),
    state: this.fb.nonNullable.control('', [Validators.maxLength(100)]),
    country: this.fb.nonNullable.control('', [Validators.maxLength(100)]),
    pincode: this.fb.nonNullable.control('', [Validators.maxLength(20)]),
    bedrooms: this.fb.control<number | null>(null),
    bathrooms: this.fb.control<number | null>(null),
    area_value: this.fb.control<number | null>(null),
    area_unit: this.fb.nonNullable.control(''),
    amenities: this.fb.nonNullable.control<string[]>([]),
    contact_person: this.fb.nonNullable.control('', [Validators.maxLength(200)]),
    contact_phone: this.fb.nonNullable.control('', [Validators.maxLength(40)]),
    contact_email: this.fb.nonNullable.control('', [Validators.email, Validators.maxLength(200)]),
  });

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id');
      if (id) {
        this.propertyId.set(id);
        this.loadForEdit(id);
      } else {
        this.propertyId.set(null);
        this.form.reset({
          title: '',
          property_type: '',
          category: '',
          description: '',
          price: null,
          currency: 'INR',
          address_line: '',
          city: '',
          state: '',
          country: '',
          pincode: '',
          bedrooms: null,
          bathrooms: null,
          area_value: null,
          area_unit: '',
          amenities: [],
          contact_person: '',
          contact_phone: '',
          contact_email: '',
        });
        this.initialImages.set([]);
      }
    });
  }

  private loadForEdit(id: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .getById(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (p) => {
          this.hydrateForm(p);
          this.initialImages.set(p.images ?? []);
          this.currentProperty.set(p);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(extractApiError(err) ?? 'Failed to load property.');
          this.loading.set(false);
        },
      });
  }

  /** Toolbar row-menu handlers. */
  protected onToolbarRefresh(): void {
    const id = this.propertyId();
    if (id) this.loadForEdit(id);
  }

  protected onToolbarOptimistic(event: { id: string; status: Property['status'] }): void {
    this.currentProperty.update((p) => (p ? { ...p, status: event.status } : p));
  }

  protected onToolbarRemoved(): void {
    this.router.navigate(['/user/properties']);
  }

  private hydrateForm(p: Property): void {
    const numeric = (v: string | number | null): number | null => {
      if (v === null || v === undefined || v === '') return null;
      const n = typeof v === 'string' ? Number(v) : v;
      return Number.isFinite(n) ? n : null;
    };
    this.form.reset({
      title: p.title,
      property_type: p.property_type,
      category: p.category,
      description: p.description ?? '',
      price: numeric(p.price),
      currency: p.currency,
      address_line: p.address_line ?? '',
      city: p.city ?? '',
      state: p.state ?? '',
      country: p.country ?? '',
      pincode: p.pincode ?? '',
      bedrooms: p.bedrooms ?? null,
      bathrooms: p.bathrooms ?? null,
      area_value: numeric(p.area_value),
      area_unit: p.area_unit ?? '',
      amenities: [...p.amenities],
      contact_person: p.contact_person ?? '',
      contact_phone: p.contact_phone ?? '',
      contact_email: p.contact_email ?? '',
    });
  }

  protected submit(): void {
    this.form.markAllAsTouched();
    if (this.form.invalid) {
      this.submitError.set('Please fill in the highlighted fields.');
      return;
    }
    this.submitError.set(null);
    this.saving.set(true);

    const raw = this.form.getRawValue();
    const payload = this.toPayload(raw);
    const id = this.propertyId();

    if (id === null) {
      this.api
        .create(payload as PropertyCreate)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (created) => {
            this.saving.set(false);
            this.snackBar.open('Property saved as draft.', 'Dismiss', { duration: 2500 });
            this.router.navigate(['/user/properties', created.id, 'edit']);
          },
          error: (err: HttpErrorResponse) => this.handleError(err, 'Could not create property'),
        });
    } else {
      this.api
        .update(id, payload as PropertyUpdate)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (updated) => {
            this.saving.set(false);
            this.hydrateForm(updated);
            this.currentProperty.set(updated);
            this.snackBar.open('Property saved.', 'Dismiss', { duration: 2500 });
          },
          error: (err: HttpErrorResponse) => this.handleError(err, 'Could not save property'),
        });
    }
  }

  private toPayload(raw: ReturnType<typeof this.form.getRawValue>): PropertyCreate {
    const blank = (v: string | null | undefined): string | null =>
      v !== null && v !== undefined && v !== '' ? v : null;
    return {
      title: raw.title,
      property_type: raw.property_type as PropertyTypeKey,
      category: raw.category as PropertyCategoryKey,
      description: blank(raw.description),
      price: raw.price,
      currency: raw.currency || null,
      address_line: blank(raw.address_line),
      city: blank(raw.city),
      state: blank(raw.state),
      country: blank(raw.country),
      pincode: blank(raw.pincode),
      bedrooms: raw.bedrooms,
      bathrooms: raw.bathrooms,
      area_value: raw.area_value,
      area_unit: blank(raw.area_unit),
      amenities: raw.amenities,
      contact_person: blank(raw.contact_person),
      contact_phone: blank(raw.contact_phone),
      contact_email: blank(raw.contact_email),
    };
  }

  private handleError(err: HttpErrorResponse, fallback: string): void {
    this.saving.set(false);
    const message = extractApiError(err) ?? fallback;
    this.submitError.set(message);
    this.snackBar.open(message, 'Dismiss', { duration: 4000 });
  }

  protected fieldError(control: keyof PropertyFormControls): string | null {
    const c = this.form.controls[control];
    if (!c.touched || c.valid) return null;
    if (c.errors?.['required']) return 'Required.';
    if (c.errors?.['email']) return 'Enter a valid email.';
    if (c.errors?.['maxlength']) {
      return `Too long (max ${c.errors['maxlength'].requiredLength}).`;
    }
    return 'Invalid value.';
  }
}

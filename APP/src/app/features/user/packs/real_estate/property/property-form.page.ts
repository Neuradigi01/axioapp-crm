import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  HostListener,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
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
import { ToastService } from '../../../../../shared/components/toast/toast.service';

import { extractApiError } from '@core/services/api-error.util';
import { LocationApiService } from '@app/services/location-api.service';
import type { ICountry, IState } from '@app/schemas/common';

import { FormToastHelper } from '../../../core/shared/forms/form-toast.helper';
import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../../core/shared/forms/mobile-select.component';
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
    MobileSelectComponent,
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
  private readonly toast = inject(ToastService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly formToast = inject(FormToastHelper);
  private readonly locationApi = inject(LocationApiService);

  protected readonly TYPE_OPTIONS = PROPERTY_TYPE_OPTIONS;
  protected readonly CATEGORY_OPTIONS = PROPERTY_CATEGORY_OPTIONS;
  protected readonly UNIT_OPTIONS = AREA_UNIT_OPTIONS;

  // Mapped to `crm-mobile-select` shape ({value, label}). The
  // canonical option arrays keep the `key` field name because a
  // handful of non-picker call-sites read it — mapping in the
  // component beats renaming everywhere.
  protected readonly typeSelectOptions: readonly MobileSelectOption[] = PROPERTY_TYPE_OPTIONS.map(
    (o) => ({ value: o.key, label: o.label }),
  );
  protected readonly categorySelectOptions: readonly MobileSelectOption[] =
    PROPERTY_CATEGORY_OPTIONS.map((o) => ({ value: o.key, label: o.label }));
  protected readonly unitSelectOptions: readonly MobileSelectOption[] = [
    { value: '', label: '—' },
    ...AREA_UNIT_OPTIONS.map((o) => ({ value: o.key, label: o.label })),
  ];

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
    price: this.fb.control<number | null>(null, [Validators.min(0)]),
    currency: this.fb.nonNullable.control('INR', [
      Validators.required,
      Validators.pattern(/^[A-Z]{3}$/),
    ]),
    address_line: this.fb.nonNullable.control('', [Validators.maxLength(500)]),
    city: this.fb.nonNullable.control('', [Validators.maxLength(100)]),
    state: this.fb.nonNullable.control('', [Validators.maxLength(100)]),
    country: this.fb.nonNullable.control('', [Validators.maxLength(100)]),
    // Postal codes vary globally (5–10 alphanumerics). Enforces "digits/letters
    // only, 3–10 chars" so free-text garbage is caught early.
    pincode: this.fb.nonNullable.control('', [
      Validators.maxLength(20),
      Validators.pattern(/^[A-Za-z0-9 -]{3,10}$/),
    ]),
    bedrooms: this.fb.control<number | null>(null, [Validators.min(0), Validators.max(50)]),
    bathrooms: this.fb.control<number | null>(null, [Validators.min(0), Validators.max(50)]),
    area_value: this.fb.control<number | null>(null, [Validators.min(0)]),
    area_unit: this.fb.nonNullable.control(''),
    amenities: this.fb.nonNullable.control<string[]>([]),
    contact_person: this.fb.nonNullable.control('', [Validators.maxLength(200)]),
    // Same E.164 rule the rest of the app uses (see custom-validators.ts).
    contact_phone: this.fb.nonNullable.control('', [
      Validators.maxLength(16),
      Validators.pattern(/^\+?[0-9]{8,15}$/),
    ]),
    contact_email: this.fb.nonNullable.control('', [Validators.email, Validators.maxLength(200)]),
  });

  // Country / State pickers — same `/location` reference data the
  // registration form uses. The property row stores plain names, so
  // option values are names (not ids); the id is only needed to fetch
  // a country's states.
  private readonly countries = signal<ICountry[]>([]);
  private readonly states = signal<IState[]>([]);
  protected readonly statesLoading = signal(false);
  private readonly countriesReady = this.loadCountries();
  /** Bumped on every states fetch so a slow response for a previously
   *  picked country can't overwrite the list for the current one. */
  private statesRequest = 0;

  private readonly countryValue = toSignal(this.form.controls.country.valueChanges, {
    initialValue: this.form.controls.country.value,
  });
  private readonly stateValue = toSignal(this.form.controls.state.valueChanges, {
    initialValue: this.form.controls.state.value,
  });
  protected readonly countryOptions = computed<MobileSelectOption[]>(() =>
    withCurrentValue(
      this.countries().map((c) => c.name),
      this.countryValue(),
    ),
  );
  protected readonly stateOptions = computed<MobileSelectOption[]>(() =>
    withCurrentValue(
      this.states().map((s) => s.name),
      this.stateValue(),
    ),
  );

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
        void this.loadStates('');
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

  /** Warn the user before they close the browser tab / hit refresh
   *  with unsaved changes. Only fires when the form is `dirty` and
   *  we're not already mid-submit. Angular router navigation isn't
   *  covered here — for that see `cancelEdit()` which prompts on
   *  the Cancel button click. */
  @HostListener('window:beforeunload', ['$event'])
  onBeforeUnload(event: BeforeUnloadEvent): void {
    if (this.form.dirty && !this.saving()) {
      event.preventDefault();
      // Legacy Chromium: setting returnValue triggers the native prompt.
      event.returnValue = '';
    }
  }

  /** Router-navigation cancel — if the form is dirty, ask before
   *  discarding. Called from the Cancel button in the footer instead
   *  of a plain `routerLink` so the confirm can intercept. */
  protected cancelEdit(): void {
    if (this.form.dirty && !this.saving()) {
      const ok = window.confirm('Discard unsaved changes and leave this page?');
      if (!ok) return;
    }
    this.router.navigate(['/user/properties']);
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
    void this.loadStates(p.country ?? '');
  }

  protected onCountryChange(): void {
    this.form.controls.state.setValue('');
    void this.loadStates(this.form.controls.country.value);
  }

  private async loadCountries(): Promise<void> {
    try {
      const res = await this.locationApi.getCountries();
      this.countries.set(res.success ? res.data : []);
    } catch {
      this.countries.set([]);
    }
  }

  /** Fetch the states for `countryName`; the State picker stays
   *  disabled until a country with states is selected. Leaves the
   *  current State value untouched so an edit-mode hydrate keeps it. */
  private async loadStates(countryName: string): Promise<void> {
    const request = ++this.statesRequest;
    const stateControl = this.form.controls.state;
    this.states.set([]);
    stateControl.disable({ emitEvent: false });
    this.statesLoading.set(!!countryName);
    if (!countryName) return;

    try {
      await this.countriesReady;
      const target = countryName.trim().toLowerCase();
      const country = this.countries().find((c) => c.name.toLowerCase() === target);
      if (!country) return;
      const res = await this.locationApi.getStates(country.id);
      if (request !== this.statesRequest || !res.success) return;
      this.states.set(res.data);
      if (res.data.length > 0) stateControl.enable({ emitEvent: false });
    } catch {
      if (request === this.statesRequest) this.states.set([]);
    } finally {
      if (request === this.statesRequest) this.statesLoading.set(false);
    }
  }

  protected submit(): void {
    this.form.markAllAsTouched();
    if (this.form.invalid) {
      this.submitError.set('Please fill in the highlighted fields.');
      this.formToast.requiredFieldsMissing();
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
            // Show the toast BEFORE navigating so it renders against
            // the current page paint; the shared toast overlay is
            // document-root and persists across the route change.
            this.toast.success('Draft saved', {
              subtitle: 'You can add images once the page reloads.',
            });
            this.router.navigate(['/user/properties', created.id, 'edit']);
          },
          error: (err: HttpErrorResponse) => this.handleError(err, 'Could not create property'),
        });
    } else {
      this.api
        .update(id, payload as PropertyUpdate)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (_updated) => {
            this.saving.set(false);
            this.toast.success('Property saved');
            // Close edit mode → back to list. Owners save + move on; if
            // they want to keep editing they click the row again.
            this.router.navigate(['/user/properties']);
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
    this.toast.error(message);
  }

  protected fieldError(control: keyof PropertyFormControls): string | null {
    const c = this.form.controls[control];
    if (!c.touched || c.valid) return null;
    if (c.errors?.['required']) return 'Required.';
    if (c.errors?.['email']) return 'Enter a valid email.';
    if (c.errors?.['maxlength']) {
      return `Too long (max ${c.errors['maxlength'].requiredLength}).`;
    }
    if (c.errors?.['min']) {
      return `Must be ${c.errors['min'].min} or more.`;
    }
    if (c.errors?.['max']) {
      return `Must be ${c.errors['max'].max} or less.`;
    }
    if (c.errors?.['pattern']) {
      // Give a helpful message per field rather than the raw regex.
      if (control === 'contact_phone') {
        return 'Enter 8–15 digits, optionally starting with +.';
      }
      if (control === 'pincode') {
        return 'Enter a valid postal code (3–10 letters/digits).';
      }
      if (control === 'currency') {
        return 'Enter a 3-letter currency code (e.g. INR, USD).';
      }
      return 'Invalid format.';
    }
    return 'Invalid value.';
  }
}

/** Map location names to picker options, appending `current` when it
 *  isn't in the reference list so a free-text value saved before the
 *  pickers existed still renders (and round-trips) instead of blanking. */
function withCurrentValue(names: readonly string[], current: string): MobileSelectOption[] {
  const options = names.map((name) => ({ value: name, label: name }));
  if (current && !names.includes(current)) options.push({ value: current, label: current });
  return options;
}

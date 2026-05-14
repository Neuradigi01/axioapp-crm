import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import {
  FormArray,
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { catchError, of, switchMap } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import {
  Appointment,
  AppointmentsApiService,
} from '../../../core/appointments/appointments-api.service';
import { ContactsApiService } from '../../../core/contacts/contacts-api.service';
import {
  FieldOpsApiService,
  FieldVisit,
  FieldVisitPhoto,
  MeasurementCopyback,
} from './field-ops-api.service';

interface MeasurementRowGroup {
  item_label: FormControl<string>;
  length_cm: FormControl<string>;
  width_cm: FormControl<string>;
  height_cm: FormControl<string>;
  notes: FormControl<string>;
}

@Component({
  selector: 'app-field-visit-detail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, ReactiveFormsModule, LucideAngularModule],
  templateUrl: './field-visit-detail.page.html',
})
export class FieldVisitDetailPageComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(FieldOpsApiService);
  private readonly appointmentsApi = inject(AppointmentsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly visit = signal<FieldVisit | null>(null);
  protected readonly appointment = signal<Appointment | null>(null);
  protected readonly contactName = signal<string | null>(null);
  protected readonly contactPhone = signal<string | null>(null);
  protected readonly photos = signal<FieldVisitPhoto[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);

  protected readonly completeOpen = signal(false);
  protected readonly completing = signal(false);
  protected readonly completeError = signal<string | null>(null);

  protected readonly uploading = signal(false);
  protected readonly uploadError = signal<string | null>(null);

  protected readonly apiOrigin = this.deriveApiOrigin();

  readonly completeForm = this.fb.group({
    notes: this.fb.control<string>('', { nonNullable: true }),
  });

  readonly measurements: FormArray<FormGroup<MeasurementRowGroup>> =
    this.fb.array<FormGroup<MeasurementRowGroup>>([]);

  protected readonly canShowMeasurements = computed(
    () => (this.visit()?.custom_order_id ?? null) !== null,
  );

  constructor() {
    this.route.paramMap
      .pipe(
        switchMap((p) => {
          const id = p.get('id');
          if (!id) return of(null);
          this.loading.set(true);
          this.loadError.set(null);
          return this.api.get(id).pipe(
            catchError((err: HttpErrorResponse) => {
              this.loadError.set(
                this.extractError(err) ?? 'Could not load visit.',
              );
              this.loading.set(false);
              return of(null);
            }),
          );
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((v) => {
        if (!v) return;
        this.visit.set(v);
        this.loading.set(false);
        this.loadAppointment(v.appointment_id);
        this.loadPhotos(v.id);
      });
  }

  protected openComplete(): void {
    this.completeError.set(null);
    this.completeOpen.set(true);
    if (this.canShowMeasurements() && this.measurements.length === 0) {
      this.addMeasurement();
    }
  }

  protected closeComplete(): void {
    this.completeOpen.set(false);
  }

  protected addMeasurement(): void {
    this.measurements.push(
      this.fb.group<MeasurementRowGroup>({
        item_label: this.fb.control<string>('', {
          nonNullable: true,
          validators: [Validators.required],
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

  protected submitComplete(): void {
    const v = this.visit();
    if (!v || this.completing()) return;
    this.completing.set(true);
    this.completeError.set(null);

    const measurements: MeasurementCopyback[] = this.canShowMeasurements()
      ? this.measurements.controls
          .map((g) => g.getRawValue())
          .filter((r) => r.item_label.trim().length > 0)
          .map((r) => ({
            item_label: r.item_label.trim(),
            length_cm: this.nullableTrim(r.length_cm),
            width_cm: this.nullableTrim(r.width_cm),
            height_cm: this.nullableTrim(r.height_cm),
            notes: this.nullableTrim(r.notes),
          }))
      : [];

    this.api
      .complete(v.id, {
        notes: this.nullableTrim(this.completeForm.controls.notes.value),
        measurements,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.completing.set(false);
          this.visit.set(updated);
          this.completeOpen.set(false);
          // Appointment status flipped server-side — re-fetch to reflect.
          this.loadAppointment(updated.appointment_id);
        },
        error: (err: HttpErrorResponse) => {
          this.completing.set(false);
          this.completeError.set(
            this.extractError(err) ?? 'Could not complete the visit.',
          );
        },
      });
  }

  protected onPhotoFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    const v = this.visit();
    if (!v) return;
    this.uploading.set(true);
    this.uploadError.set(null);
    this.api
      .uploadPhoto(v.id, file, null)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (photo) => {
          this.uploading.set(false);
          this.photos.update((rows) => [photo, ...rows]);
        },
        error: (err: HttpErrorResponse) => {
          this.uploading.set(false);
          this.uploadError.set(
            this.extractError(err) ?? 'Could not upload photo.',
          );
        },
      });
  }

  protected absoluteUrl(path: string): string {
    if (/^https?:\/\//.test(path)) return path;
    return `${this.apiOrigin}${path}`;
  }

  protected formatDateTime(iso: string | null | undefined): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  protected purposeBadgeClass(purpose: string): string {
    switch (purpose) {
      case 'measurement':
        return 'bg-sky-100 text-sky-700 ring-sky-200';
      case 'installation':
        return 'bg-amber-100 text-amber-700 ring-amber-200';
      case 'inspection':
        return 'bg-violet-100 text-violet-700 ring-violet-200';
      default:
        return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
    }
  }

  private loadAppointment(id: string): void {
    this.appointmentsApi
      .get(id)
      .pipe(
        catchError(() => of(null)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((a) => {
        if (!a) return;
        this.appointment.set(a);
        this.contactsApi
          .get(a.contact_id)
          .pipe(
            catchError(() => of(null)),
            takeUntilDestroyed(this.destroyRef),
          )
          .subscribe((c) => {
            if (c) {
              this.contactName.set(c.full_name);
              this.contactPhone.set(c.phone);
            }
          });
      });
  }

  private loadPhotos(id: string): void {
    this.api
      .listPhotos(id)
      .pipe(
        catchError(() => of<FieldVisitPhoto[]>([])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((rows) => this.photos.set(rows));
  }

  private deriveApiOrigin(): string {
    try {
      return new URL(environment.apiBaseUrl, window.location.origin).origin;
    } catch {
      return '';
    }
  }

  private nullableTrim(v: string | null | undefined): string | null {
    if (v === null || v === undefined) return null;
    const t = v.trim();
    return t.length === 0 ? null : t;
  }

  private extractError(err: HttpErrorResponse): string | null {
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const candidate =
        (body as { message?: string; detail?: unknown }).message
        ?? (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}

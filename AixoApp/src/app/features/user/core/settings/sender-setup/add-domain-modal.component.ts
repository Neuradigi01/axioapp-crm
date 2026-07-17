/**
 * Add-domain modal (Step 07b).
 *
 * Single input — the naked domain (e.g. ``yourshop.com``). Client-side
 * validation matches the backend's RFC-1035 shape check to avoid a
 * pointless roundtrip; the server still enforces on POST (loose but
 * bounded regex, plus a lower/rstrip normalisation).
 */
import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

// Same shape the backend enforces in `email_sender_setup/schemas.py`.
const DOMAIN_PATTERN = /^(?=.{1,253}$)(?:(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.)+(?:[A-Za-z]{2,63})$/;

@Component({
  selector: 'app-sender-add-domain-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReactiveFormsModule],
  templateUrl: './add-domain-modal.component.html',
})
export class AddDomainModalComponent {
  readonly creating = input<boolean>(false);
  readonly submitted = output<string>();
  readonly cancelled = output<void>();

  private readonly fb = inject(FormBuilder);

  protected readonly form: {
    domain: FormControl<string>;
  } = {
    domain: this.fb.control<string>('', {
      nonNullable: true,
      validators: [
        Validators.required,
        Validators.minLength(3),
        Validators.maxLength(253),
        Validators.pattern(DOMAIN_PATTERN),
      ],
    }),
  };

  onBackdropClick(event: MouseEvent): void {
    if (event.target === event.currentTarget && !this.creating()) {
      this.cancelled.emit();
    }
  }

  submit(): void {
    if (this.creating()) return;
    if (this.form.domain.invalid) {
      this.form.domain.markAsTouched();
      return;
    }
    const normalised = (this.form.domain.value || '').trim().toLowerCase().replace(/\.+$/, '');
    this.submitted.emit(normalised);
  }
}

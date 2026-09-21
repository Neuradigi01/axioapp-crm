/**
 * Claim-domain modal (tasks/email-sending-domains Step 7).
 *
 * Owner-only flow — the parent tab enforces this by only rendering
 * when ``auth.hasPermission('email.sending_domains.manage')``. This
 * component doesn't repeat the permission check.
 *
 * Client-side validation mirrors the backend's ``ClaimDomainIn``
 * shape (RFC-1035 labels; no scheme; no path). The server still
 * validates on POST so this is a UX-only tightening — a hand-crafted
 * request that bypasses the modal still bounces at 422.
 */
import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { commonValidators } from '../../shared/validators';
import type { ClaimDomainRequest } from './models';

@Component({
  selector: 'app-claim-domain-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReactiveFormsModule],
  templateUrl: './claim-domain-modal.component.html',
})
export class ClaimDomainModalComponent {
  readonly creating = input<boolean>(false);
  readonly submitted = output<ClaimDomainRequest>();
  readonly cancelled = output<void>();

  private readonly fb = inject(FormBuilder);

  protected readonly form: {
    domain: FormControl<string>;
    region: FormControl<'us' | 'eu'>;
  } = {
    domain: this.fb.control<string>('', {
      nonNullable: true,
      validators: [
        Validators.required,
        Validators.minLength(3),
        Validators.maxLength(253),
        commonValidators.hostnameApex,
      ],
    }),
    region: this.fb.control<'us' | 'eu'>('us', { nonNullable: true }),
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
    const domain = (this.form.domain.value || '').trim().toLowerCase().replace(/\.+$/, '');
    this.submitted.emit({ domain, region: this.form.region.value });
  }
}

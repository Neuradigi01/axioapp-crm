import { Component, ChangeDetectionStrategy, signal, inject } from '@angular/core';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';
import { AuthApiService } from '@app/services/auth-api.service';
import { getRoute } from '@core/services/routes-helper.service';
import { SNACKBAR_DURATION_LONG, SNACKBAR_ACTION } from '@core/constants/app.constants';
import { MSG_PASSWORD_RESET_SENT } from '@core/constants/messages.constants';

@Component({
  selector: 'app-forgot-password',
  templateUrl: './forgot-password.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, LucideAngularModule, ValidationMessageComponent],
})
export class ForgotPasswordComponent {
  private readonly fb = inject(FormBuilder);
  private readonly authApi = inject(AuthApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly forgotForm: FormGroup = this.fb.group({
    identifier: ['', Validators.required],
  });

  readonly isLoading = signal(false);
  readonly submitted = signal(false);

  readonly loginUrl = getRoute('login').url;

  async onSubmit(): Promise<void> {
    if (this.forgotForm.invalid) {
      this.forgotForm.markAllAsTouched();
      return;
    }

    this.isLoading.set(true);

    try {
      await this.authApi.forgotPassword(this.forgotForm.value);
    } catch {
      // Intentionally ignore errors to prevent email enumeration
    } finally {
      this.isLoading.set(false);
      this.submitted.set(true);
      this.snackBar.open(MSG_PASSWORD_RESET_SENT, SNACKBAR_ACTION, {
        duration: SNACKBAR_DURATION_LONG,
      });
    }
  }
}

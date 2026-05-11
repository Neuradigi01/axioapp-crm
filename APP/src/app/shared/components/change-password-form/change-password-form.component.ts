import { Component, ChangeDetectionStrategy, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { FormCardComponent } from '@shared/components/form-card/form-card.component';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';
import { PasswordToggleDirective } from '@shared/directives/password-toggle.directive';
import { matchFieldValidator } from '@shared/validators/custom-validators';
import { ChangePasswordApiService } from '@app/services/change-password-api.service';
import { SNACKBAR_DURATION, SNACKBAR_ACTION } from '@core/constants/app.constants';
import { MSG_ERROR_GENERIC, MSG_PASSWORD_CHANGED, MSG_PASSWORD_CHANGE_FAILED } from '@core/constants/messages.constants';

@Component({
  selector: 'app-change-password-form',
  templateUrl: './change-password-form.component.html',
  styleUrl: './change-password-form.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    FormCardComponent,
    ValidationMessageComponent,
    PasswordToggleDirective,
  ],
})
export class ChangePasswordFormComponent {
  private readonly fb = inject(FormBuilder);
  private readonly changePasswordApi = inject(ChangePasswordApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly passwordForm: FormGroup = this.fb.group({
    old_password: ['', Validators.required],
    new_password: ['', [Validators.required, Validators.minLength(8)]],
    confirm_password: ['', [Validators.required, matchFieldValidator('new_password')]],
  });

  readonly isLoading = signal(false);

  async onSubmit(): Promise<void> {
    if (this.passwordForm.invalid) {
      this.passwordForm.markAllAsTouched();
      return;
    }

    this.isLoading.set(true);
    const payload = {
      old_password: this.passwordForm.get('old_password')!.value,
      new_password: this.passwordForm.get('new_password')!.value,
    };

    try {
      const response = await this.changePasswordApi.changePassword(payload);
      if (response.success) {
        this.snackBar.open(MSG_PASSWORD_CHANGED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.passwordForm.reset();
      } else {
        this.snackBar.open(response.message || MSG_PASSWORD_CHANGE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }
}

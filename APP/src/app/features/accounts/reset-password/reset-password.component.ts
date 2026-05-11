import { Component, ChangeDetectionStrategy, signal, inject, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';
import { PasswordToggleDirective } from '@shared/directives/password-toggle.directive';
import { matchFieldValidator } from '@shared/validators/custom-validators';
import { AuthApiService } from '@app/services/auth-api.service';
import { getRoute } from '@core/services/routes-helper.service';
import { SNACKBAR_DURATION, SNACKBAR_ACTION } from '@core/constants/app.constants';
import { MSG_ERROR_GENERIC, MSG_PASSWORD_RESET_SUCCESS, MSG_PASSWORD_RESET_FAILED } from '@core/constants/messages.constants';

@Component({
  selector: 'app-reset-password',
  templateUrl: './reset-password.component.html',
  styleUrl: './reset-password.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    ValidationMessageComponent,
    PasswordToggleDirective,
  ],
})
export class ResetPasswordComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly authApi = inject(AuthApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly snackBar = inject(MatSnackBar);

  readonly resetForm: FormGroup = this.fb.group({
    new_password: ['', [Validators.required, Validators.minLength(8)]],
    confirm_password: ['', [Validators.required, matchFieldValidator('new_password')]],
  });

  readonly isLoading = signal(false);
  readonly tokenError = signal(false);

  readonly loginUrl = getRoute('login').url;

  private token = '';

  ngOnInit(): void {
    this.token = this.route.snapshot.queryParamMap.get('token') ?? '';
    if (!this.token) {
      this.tokenError.set(true);
    }
  }

  async onSubmit(): Promise<void> {
    if (this.resetForm.invalid || !this.token) return;

    this.isLoading.set(true);

    try {
      const response = await this.authApi.resetPassword({
        token: this.token,
        new_password: this.resetForm.value.new_password,
      });

      if (response.success) {
        this.snackBar.open(response.message || MSG_PASSWORD_RESET_SUCCESS, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.router.navigate([this.loginUrl]);
      } else {
        const msg = response.message || MSG_PASSWORD_RESET_FAILED;
        if (msg.toLowerCase().includes('expired') || msg.toLowerCase().includes('invalid')) {
          this.tokenError.set(true);
        }
        this.snackBar.open(msg, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }
}

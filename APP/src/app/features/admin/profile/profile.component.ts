import { Component, ChangeDetectionStrategy, inject, signal, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { FormCardComponent } from '@shared/components/form-card/form-card.component';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';
import { AdminApiService } from '@app/services/admin-api.service';
import { AppSettings } from '@app/app.settings';
import { SNACKBAR_DURATION, SNACKBAR_ACTION } from '@core/constants/app.constants';
import { MSG_ERROR_GENERIC, MSG_PROFILE_UPDATED, MSG_PROFILE_UPDATE_FAILED, MSG_PROFILE_IMAGE_UPDATED, MSG_PROFILE_IMAGE_REMOVED } from '@core/constants/messages.constants';

@Component({
  selector: 'app-admin-profile',
  templateUrl: './profile.component.html',
  styleUrl: './profile.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    FormCardComponent,
    ValidationMessageComponent,
  ],
})
export class ProfileComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly adminApi = inject(AdminApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly profileForm: FormGroup = this.fb.group({
    admin_user_id: [{ value: '', disabled: true }],
    name: [{ value: '', disabled: true }],
    email: ['', [Validators.required, Validators.email]],
    mobile_no: [''],
  });

  readonly isLoading = signal(false);
  readonly isSaving = signal(false);
  readonly isUploading = signal(false);
  readonly profileImageUrl = signal<string | null>(null);

  async ngOnInit(): Promise<void> {
    this.isLoading.set(true);
    try {
      const response = await this.adminApi.getProfile();
      if (response.success && response.data) {
        const data = response.data;
        this.profileForm.patchValue({
          admin_user_id: data.admin_user_id,
          name: data.name,
          email: data.email,
          mobile_no: data.mobile_no || '',
        });
        this.setProfileImageUrl(data.profile_image);
      }
    } catch {
      // API error handled by interceptor
    } finally {
      this.isLoading.set(false);
    }
  }

  async onSubmit(): Promise<void> {
    if (this.profileForm.invalid) {
      this.profileForm.markAllAsTouched();
      return;
    }

    this.isSaving.set(true);
    const payload = {
      email: this.profileForm.get('email')!.value,
      mobile_no: this.profileForm.get('mobile_no')!.value || null,
    };

    try {
      const response = await this.adminApi.updateProfile(payload);
      if (response.success) {
        this.snackBar.open(MSG_PROFILE_UPDATED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      } else {
        this.snackBar.open(response.message || MSG_PROFILE_UPDATE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isSaving.set(false);
    }
  }

  async onFileSelected(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    // Reset input so the same file can be re-selected
    input.value = '';

    this.isUploading.set(true);
    try {
      const response = await this.adminApi.uploadProfileImage(file);
      if (response.success && response.data) {
        this.setProfileImageUrl(response.data.profile_image);
        this.snackBar.open(MSG_PROFILE_IMAGE_UPDATED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      } else {
        this.snackBar.open(response.message || 'Failed to upload image', SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isUploading.set(false);
    }
  }

  async onRemoveImage(): Promise<void> {
    this.isUploading.set(true);
    try {
      const response = await this.adminApi.removeProfileImage();
      if (response.success) {
        this.profileImageUrl.set(null);
        this.snackBar.open(MSG_PROFILE_IMAGE_REMOVED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      } else {
        this.snackBar.open(response.message || 'Failed to remove image', SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isUploading.set(false);
    }
  }

  private setProfileImageUrl(relativePath: string | null): void {
    if (relativePath) {
      this.profileImageUrl.set(`${AppSettings.StaticBaseUrl}/${relativePath}`);
    } else {
      this.profileImageUrl.set(null);
    }
  }
}

import { Component, ChangeDetectionStrategy, inject, signal, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { FormCardComponent } from '@shared/components/form-card/form-card.component';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';
import { AdminApiService } from '@app/services/admin-api.service';
import { getRoute } from '@core/services/routes-helper.service';
import { SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_ERROR_LOAD_FAILED,
  MSG_SUB_ADMIN_UPDATED,
  MSG_SUB_ADMIN_UPDATE_FAILED,
} from '@core/constants/messages.constants';

@Component({
  selector: 'app-admin-edit-sub-admin',
  templateUrl: './edit-sub-admin.component.html',
  styleUrl: './edit-sub-admin.component.scss',
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
  ],
})
export class EditSubAdminComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly adminApi = inject(AdminApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly editForm: FormGroup = this.fb.group({
    admin_user_id: [{ value: '', disabled: true }],
    name: ['', [Validators.required, Validators.maxLength(100)]],
    email: ['', Validators.email],
    mobile_no: [''],
  });

  readonly isLoading = signal(false);
  readonly isSaving = signal(false);

  private adminId = '';

  ngOnInit(): void {
    this.adminId = this.route.snapshot.params['id'];
    this.loadDetail();
  }

  async loadDetail(): Promise<void> {
    this.isLoading.set(true);
    try {
      const res = await this.adminApi.getSubAdminDetail(this.adminId);
      if (res.success) {
        this.editForm.patchValue({
          admin_user_id: res.data.admin_user_id,
          name: res.data.name,
          email: res.data.email ?? '',
          mobile_no: res.data.mobile_no ?? '',
        });
      } else {
        this.snackBar.open(res.message || MSG_ERROR_LOAD_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  async onSubmit(): Promise<void> {
    if (this.editForm.invalid) {
      this.editForm.markAllAsTouched();
      return;
    }

    this.isSaving.set(true);
    const val = this.editForm.getRawValue();

    try {
      const res = await this.adminApi.updateSubAdmin(this.adminId, {
        name: val.name,
        email: val.email || null,
        mobile_no: val.mobile_no || null,
      });

      if (res.success) {
        this.snackBar.open(MSG_SUB_ADMIN_UPDATED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.router.navigate([getRoute('sub_admin').url]);
      } else {
        this.snackBar.open(res.message || MSG_SUB_ADMIN_UPDATE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isSaving.set(false);
    }
  }

  goBack(): void {
    this.router.navigate([getRoute('sub_admin').url]);
  }
}

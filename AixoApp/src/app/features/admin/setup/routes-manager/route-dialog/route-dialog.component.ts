import { Component, ChangeDetectionStrategy, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';
import { SetupApiService } from '@app/services/setup-api.service';
import { IRouteManagement } from '@app/schemas/route-management';
import { ROUTE_USER_TYPE_OPTIONS, SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_ROUTE_DELETED,
  MSG_ROUTE_DELETE_FAILED,
  MSG_ROUTE_SAVED,
  MSG_ROUTE_SAVE_FAILED,
} from '@core/constants/messages.constants';

interface RouteDialogData {
  mode: 'add' | 'edit';
  route?: IRouteManagement;
}

@Component({
  selector: 'app-route-dialog',
  templateUrl: './route-dialog.component.html',
  styleUrl: './route-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatCheckboxModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
    ValidationMessageComponent,
  ],
})
export class RouteDialogComponent {
  private readonly fb = inject(FormBuilder);
  private readonly dialogRef = inject(MatDialogRef<RouteDialogComponent>);
  private readonly data: RouteDialogData = inject(MAT_DIALOG_DATA);
  private readonly setupApi = inject(SetupApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly isEditMode = this.data.mode === 'edit';
  readonly isSaving = signal(false);
  readonly userTypeOptions = ROUTE_USER_TYPE_OPTIONS;

  readonly form: FormGroup = this.fb.group({
    control_id: [this.data.route?.control_id ?? '', Validators.required],
    name: [this.data.route?.name ?? '', Validators.required],
    path: [this.data.route?.path ?? '', Validators.required],
    url: [this.data.route?.url ?? '', Validators.required],
    parent_id: [this.data.route?.parent_id ?? 0],
    nav_parent_id: [this.data.route?.nav_parent_id ?? 0],
    user_type: [this.data.route?.user_type ?? 'Admin'],
    mat_icon: [this.data.route?.mat_icon ?? ''],
    description: [this.data.route?.description ?? ''],
    is_nav_menu_item: [this.data.route?.is_nav_menu_item ?? false],
    is_compulsory: [this.data.route?.is_compulsory ?? false],
    order_no: [this.data.route?.order_no ?? 0],
  });

  async onSave(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    this.isSaving.set(true);
    const formVal = this.form.value;

    const payload = {
      ...formVal,
      ...(this.isEditMode ? { id: this.data.route!.id } : {}),
    };

    try {
      const res = await this.setupApi.saveRoute(payload);
      if (res.success) {
        this.snackBar.open(MSG_ROUTE_SAVED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.dialogRef.close(true);
      } else {
        this.snackBar.open(res.message || MSG_ROUTE_SAVE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isSaving.set(false);
    }
  }

  async onDelete(): Promise<void> {
    if (!confirm(`Delete route "${this.data.route!.name}" (${this.data.route!.control_id})?`)) return;

    this.isSaving.set(true);
    try {
      const res = await this.setupApi.deleteRoute(this.data.route!.id);
      if (res.success) {
        this.snackBar.open(MSG_ROUTE_DELETED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.dialogRef.close(true);
      } else {
        this.snackBar.open(res.message || MSG_ROUTE_DELETE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isSaving.set(false);
    }
  }

  onCancel(): void {
    this.dialogRef.close(false);
  }
}

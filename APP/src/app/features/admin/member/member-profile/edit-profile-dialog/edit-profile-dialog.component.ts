import { Component, ChangeDetectionStrategy, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';
import { IMemberDetail } from '@app/schemas/admin';

@Component({
  selector: 'app-edit-profile-dialog',
  templateUrl: './edit-profile-dialog.component.html',
  styleUrl: './edit-profile-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    ValidationMessageComponent,
  ],
})
export class EditProfileDialogComponent {
  private readonly fb = inject(FormBuilder);
  private readonly dialogRef = inject(MatDialogRef<EditProfileDialogComponent>);
  private readonly data: IMemberDetail = inject(MAT_DIALOG_DATA);

  readonly isSaving = signal(false);

  readonly form: FormGroup = this.fb.group({
    first_name: [this.data.first_name, [Validators.required, Validators.maxLength(100)]],
    last_name: [this.data.last_name, [Validators.required, Validators.maxLength(100)]],
    email: [this.data.email, [Validators.required, Validators.email]],
    mobile_no: [this.data.mobile_no || ''],
  });

  onCancel(): void {
    this.dialogRef.close(null);
  }

  onConfirm(): void {
    if (this.form.valid) {
      const val = this.form.value;
      this.dialogRef.close({
        first_name: val.first_name.trim(),
        last_name: val.last_name.trim(),
        email: val.email.trim(),
        mobile_no: val.mobile_no?.trim() || null,
      });
    }
  }
}

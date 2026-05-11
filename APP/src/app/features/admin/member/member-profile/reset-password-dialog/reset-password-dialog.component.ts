import { Component, ChangeDetectionStrategy, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatIconModule } from '@angular/material/icon';
import { PasswordToggleDirective } from '@shared/directives/password-toggle.directive';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';

@Component({
  selector: 'app-reset-password-dialog',
  templateUrl: './reset-password-dialog.component.html',
  styleUrl: './reset-password-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule,
    PasswordToggleDirective,
    ValidationMessageComponent,
  ],
})
export class ResetPasswordDialogComponent {
  private readonly fb = inject(FormBuilder);
  private readonly dialogRef = inject(MatDialogRef<ResetPasswordDialogComponent>);

  readonly isSaving = signal(false);

  readonly form: FormGroup = this.fb.group({
    new_password: ['', [Validators.required, Validators.minLength(8)]],
  });

  onCancel(): void {
    this.dialogRef.close(null);
  }

  onConfirm(): void {
    if (this.form.valid) {
      this.dialogRef.close(this.form.value.new_password);
    }
  }
}

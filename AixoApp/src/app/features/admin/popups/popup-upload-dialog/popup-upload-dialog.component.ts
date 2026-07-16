import { Component, ChangeDetectionStrategy, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';
import { PopupApiService } from '@app/services/popup-api.service';
import { NEWS_USER_TYPE_FORM_OPTIONS, SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_POPUP_CREATED,
  MSG_POPUP_CREATE_FAILED,
} from '@core/constants/messages.constants';

@Component({
  selector: 'app-popup-upload-dialog',
  templateUrl: './popup-upload-dialog.component.html',
  styleUrl: './popup-upload-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    MatDialogModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule,
    MatSelectModule,
  ],
})
export class PopupUploadDialogComponent {
  private readonly dialogRef = inject(MatDialogRef<PopupUploadDialogComponent>);
  private readonly popupApi = inject(PopupApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly isSaving = signal(false);
  readonly previewUrl = signal<string | null>(null);

  selectedFile: File | null = null;
  title = '';
  userType = 'All';

  readonly acceptTypes = '.png,.jpg,.jpeg,.gif';
  readonly userTypeOptions = NEWS_USER_TYPE_FORM_OPTIONS;

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files?.length) return;

    this.selectedFile = input.files[0];

    const reader = new FileReader();
    reader.onload = () => {
      this.previewUrl.set(reader.result as string);
    };
    reader.readAsDataURL(this.selectedFile);
  }

  async onUpload(): Promise<void> {
    if (!this.selectedFile) return;

    this.isSaving.set(true);
    try {
      const res = await this.popupApi.createPopup(
        this.selectedFile,
        this.userType,
        this.title.trim() || undefined,
      );

      if (res.success) {
        this.snackBar.open(MSG_POPUP_CREATED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.dialogRef.close(true);
      } else {
        this.snackBar.open(res.message || MSG_POPUP_CREATE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
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

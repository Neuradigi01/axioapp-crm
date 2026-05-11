import { Component, ChangeDetectionStrategy, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';
import { NewsApiService } from '@app/services/news-api.service';
import { NEWS_USER_TYPE_FORM_OPTIONS, SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_NEWS_CREATED,
  MSG_NEWS_CREATE_FAILED,
  MSG_NEWS_UPDATED,
  MSG_NEWS_UPDATE_FAILED,
} from '@core/constants/messages.constants';
import { INews } from '@app/schemas/news';

interface NewsDialogData {
  mode: 'add' | 'edit';
  news?: INews;
}

@Component({
  selector: 'app-news-dialog',
  templateUrl: './news-dialog.component.html',
  styleUrl: './news-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    ValidationMessageComponent,
  ],
})
export class NewsDialogComponent {
  private readonly fb = inject(FormBuilder);
  private readonly dialogRef = inject(MatDialogRef<NewsDialogComponent>);
  private readonly data: NewsDialogData = inject(MAT_DIALOG_DATA);
  private readonly newsApi = inject(NewsApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly isEditMode = this.data.mode === 'edit';
  readonly isSaving = signal(false);
  readonly userTypeOptions = NEWS_USER_TYPE_FORM_OPTIONS;

  readonly form: FormGroup = this.fb.group({
    heading: [this.data.news?.heading ?? '', Validators.required],
    details: [this.data.news?.details ?? '', Validators.required],
    priority: [this.data.news?.priority ?? 0],
    user_type: [this.data.news?.user_type ?? 'All'],
  });

  async onSave(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    this.isSaving.set(true);
    const formVal = this.form.value;

    try {
      let res;
      if (this.isEditMode) {
        res = await this.newsApi.updateNews(this.data.news!.id, formVal);
      } else {
        res = await this.newsApi.createNews(formVal);
      }

      if (res.success) {
        this.snackBar.open(
          this.isEditMode ? MSG_NEWS_UPDATED : MSG_NEWS_CREATED,
          SNACKBAR_ACTION,
          { duration: SNACKBAR_DURATION },
        );
        this.dialogRef.close(true);
      } else {
        this.snackBar.open(
          res.message || (this.isEditMode ? MSG_NEWS_UPDATE_FAILED : MSG_NEWS_CREATE_FAILED),
          SNACKBAR_ACTION,
          { duration: SNACKBAR_DURATION },
        );
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

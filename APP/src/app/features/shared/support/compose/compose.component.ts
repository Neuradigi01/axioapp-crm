import { Component, ChangeDetectionStrategy, inject, signal, viewChild, computed } from '@angular/core';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { FormCardComponent } from '@shared/components/form-card/form-card.component';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';
import { FileUploadComponent } from '@shared/components/file-upload/file-upload.component';
import { TicketApiService } from '@app/services/ticket-api.service';
import { SharedService } from '@core/services/shared.service';
import { getRoute } from '@core/services/routes-helper.service';
import { ROLE_ADMIN, SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_TICKET_COMPOSED,
  MSG_TICKET_COMPOSE_FAILED,
  MSG_TICKET_UPLOAD_FAILED,
} from '@core/constants/messages.constants';

@Component({
  selector: 'app-support-compose',
  templateUrl: './compose.component.html',
  styleUrl: './compose.component.scss',
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
    FileUploadComponent,
  ],
})
export class ComposeComponent {
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);
  private readonly ticketApi = inject(TicketApiService);
  private readonly shared = inject(SharedService);
  private readonly snackBar = inject(MatSnackBar);

  readonly fileUpload = viewChild<FileUploadComponent>('fileUpload');
  readonly isAdmin = computed(() => this.shared.userDetails?.role === ROLE_ADMIN);

  readonly composeForm: FormGroup = this.fb.group({
    to_user_id: [''],
    subject: ['', Validators.required],
    message: ['', Validators.required],
  });

  readonly isSaving = signal(false);
  private attachedFiles: File[] = [];

  onFilesChanged(files: File[]): void {
    this.attachedFiles = files;
  }

  async onSubmit(): Promise<void> {
    if (this.isAdmin() && !this.composeForm.value.to_user_id?.trim()) {
      this.composeForm.controls['to_user_id'].setErrors({ required: true });
      this.composeForm.markAllAsTouched();
      return;
    }

    if (this.composeForm.invalid) {
      this.composeForm.markAllAsTouched();
      return;
    }

    this.isSaving.set(true);
    const formVal = this.composeForm.value;

    try {
      let attachments: { stored_name: string; file_name: string; file_size: number; mime_type: string }[] = [];

      if (this.attachedFiles.length > 0) {
        const uploadRes = await this.ticketApi.uploadAttachments(this.attachedFiles);
        if (!uploadRes.success) {
          this.snackBar.open(uploadRes.message || MSG_TICKET_UPLOAD_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
          this.isSaving.set(false);
          return;
        }
        attachments = uploadRes.data;
      }

      const payload: { subject: string; message: string; attachments: typeof attachments; to_user_id?: string } = {
        subject: formVal.subject,
        message: formVal.message,
        attachments,
      };

      if (this.isAdmin()) {
        payload.to_user_id = formVal.to_user_id;
      }

      const res = await this.ticketApi.compose(payload);

      if (res.success) {
        this.snackBar.open(MSG_TICKET_COMPOSED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        const routeKey = this.isAdmin() ? 'admin_support_tickets' : 'user_support_tickets';
        this.router.navigate([getRoute(routeKey).url]);
      } else {
        this.snackBar.open(res.message || MSG_TICKET_COMPOSE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isSaving.set(false);
    }
  }

  goBack(): void {
    const routeKey = this.isAdmin() ? 'admin_support_tickets' : 'user_support_tickets';
    this.router.navigate([getRoute(routeKey).url]);
  }
}

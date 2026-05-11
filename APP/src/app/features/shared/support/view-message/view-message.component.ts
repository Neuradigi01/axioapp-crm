import { Component, ChangeDetectionStrategy, inject, signal, computed, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { DatePipe } from '@angular/common';
import { firstValueFrom } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { AttachmentListComponent } from '@shared/components/attachment-list/attachment-list.component';
import { FileUploadComponent } from '@shared/components/file-upload/file-upload.component';
import { TicketApiService } from '@app/services/ticket-api.service';
import { SharedService } from '@core/services/shared.service';
import { getRoute } from '@core/services/routes-helper.service';
import { ConfirmationDialogComponent } from '@shared/components/confirmation-dialog/confirmation-dialog.component';
import { IConfirmDialogData } from '@app/schemas/shared';
import { BADGE_MAP, ROLE_ADMIN, SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_ERROR_LOAD_FAILED,
  MSG_TICKET_REPLY_SENT,
  MSG_TICKET_REPLY_FAILED,
  MSG_TICKET_UPLOAD_FAILED,
  MSG_TICKET_STATUS_UPDATED,
  MSG_TICKET_STATUS_UPDATE_FAILED,
} from '@core/constants/messages.constants';
import { ITicketDetail, IThreadMessage } from '@app/schemas/ticket';

const STATUS_TRANSITIONS: Record<string, string[]> = {
  'Open': ['In Progress', 'Resolved', 'Closed'],
  'In Progress': ['Resolved', 'Closed'],
  'Resolved': ['In Progress', 'Closed'],
};

@Component({
  selector: 'app-support-view-message',
  templateUrl: './view-message.component.html',
  styleUrl: './view-message.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DatePipe,
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatSelectModule,
    MatFormFieldModule,
    MatProgressSpinnerModule,
    AttachmentListComponent,
    FileUploadComponent,
  ],
})
export class ViewMessageComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly ticketApi = inject(TicketApiService);
  private readonly shared = inject(SharedService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);

  readonly isAdmin = computed(() => this.shared.userDetails?.role === ROLE_ADMIN);

  readonly ticket = signal<ITicketDetail | null>(null);
  readonly thread = signal<IThreadMessage[]>([]);
  readonly isLoading = signal(false);
  readonly isSending = signal(false);
  readonly isUpdatingStatus = signal(false);
  readonly showAttachments = signal(false);
  readonly badgeMap = BADGE_MAP;

  readonly availableStatuses = computed(() => {
    const currentStatus = this.ticket()?.status;
    if (!currentStatus) return [];
    return STATUS_TRANSITIONS[currentStatus] || [];
  });

  replyMessage = '';
  private replyFiles: File[] = [];
  private ticketId = 0;

  ngOnInit(): void {
    this.ticketId = Number(this.route.snapshot.paramMap.get('id'));
    this.loadTicket();
  }

  async loadTicket(): Promise<void> {
    this.isLoading.set(true);
    try {
      const res = await this.ticketApi.getTicketDetail(this.ticketId);
      if (res.success && res.data) {
        this.ticket.set(res.data);
        this.thread.set(res.data.thread);
      } else {
        this.snackBar.open(res.message || MSG_ERROR_LOAD_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  onReplyFilesChanged(files: File[]): void {
    this.replyFiles = files;
  }

  async sendReply(): Promise<void> {
    if (!this.replyMessage.trim()) return;

    this.isSending.set(true);
    try {
      let attachments: { stored_name: string; file_name: string; file_size: number; mime_type: string }[] = [];

      if (this.replyFiles.length > 0) {
        const uploadRes = await this.ticketApi.uploadAttachments(this.replyFiles);
        if (!uploadRes.success) {
          this.snackBar.open(uploadRes.message || MSG_TICKET_UPLOAD_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
          this.isSending.set(false);
          return;
        }
        attachments = uploadRes.data;
      }

      const res = await this.ticketApi.reply(this.ticketId, {
        message: this.replyMessage,
        attachments,
      });

      if (res.success) {
        this.snackBar.open(MSG_TICKET_REPLY_SENT, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.replyMessage = '';
        this.replyFiles = [];
        this.loadTicket();
      } else {
        this.snackBar.open(res.message || MSG_TICKET_REPLY_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isSending.set(false);
    }
  }

  async onStatusChange(newStatus: string): Promise<void> {
    if (newStatus === 'Closed') {
      const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
        data: {
          title: 'Close Ticket',
          message: 'Are you sure you want to close this ticket? Users will no longer be able to reply.',
          confirmText: 'Close Ticket',
          cancelText: 'Cancel',
          color: 'warn',
        } as IConfirmDialogData,
      });

      const confirmed = await firstValueFrom(dialogRef.afterClosed());
      if (!confirmed) return;
    }

    this.isUpdatingStatus.set(true);
    try {
      const res = await this.ticketApi.updateStatus(this.ticketId, { status: newStatus });
      if (res.success) {
        this.snackBar.open(MSG_TICKET_STATUS_UPDATED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.loadTicket();
      } else {
        this.snackBar.open(res.message || MSG_TICKET_STATUS_UPDATE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isUpdatingStatus.set(false);
    }
  }

  isOwnMessage(msg: IThreadMessage): boolean {
    const userId = this.shared.userDetails?.userId;
    return msg.from_id === userId;
  }

  getSenderLabel(msg: IThreadMessage): string {
    if (this.isOwnMessage(msg)) return 'You';
    return msg.from_type === 'Admin' ? 'Admin' : 'User';
  }

  getAvatarInitial(msg: IThreadMessage): string {
    if (this.isOwnMessage(msg)) return 'Y';
    return msg.from_type === 'Admin' ? 'A' : 'U';
  }

  toggleAttachments(): void {
    this.showAttachments.update(v => !v);
  }

  getStatusBadge(status: string): { color: string; bgVar: string; label: string } {
    const key = status.toLowerCase();
    const badge = this.badgeMap[key];
    return badge ? { ...badge, label: status } : { color: 'var(--page-text)', bgVar: 'var(--surface-2)', label: status };
  }

  isClosed(): boolean {
    return this.ticket()?.status?.toLowerCase() === 'closed';
  }

  goBack(): void {
    const routeKey = this.isAdmin() ? 'admin_support_tickets' : 'user_support_tickets';
    this.router.navigate([getRoute(routeKey).url]);
  }
}

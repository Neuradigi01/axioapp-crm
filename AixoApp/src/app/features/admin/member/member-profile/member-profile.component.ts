import { Component, ChangeDetectionStrategy, inject, signal, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { DatePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { getRoute } from '@core/services/routes-helper.service';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { MatDividerModule } from '@angular/material/divider';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { FormCardComponent } from '@shared/components/form-card/form-card.component';
import { ConfirmationDialogComponent } from '@shared/components/confirmation-dialog/confirmation-dialog.component';
import { AdminApiService } from '@app/services/admin-api.service';
import { AuthService } from '@core/services/auth.service';
import { BADGE_MAP, SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_ERROR_LOAD_FAILED,
  MSG_USER_STATUS_UPDATED,
  MSG_USER_STATUS_UPDATE_FAILED,
  MSG_USER_PASSWORD_RESET,
  MSG_USER_PASSWORD_RESET_FAILED,
  MSG_USER_PROFILE_UPDATED,
  MSG_USER_PROFILE_UPDATE_FAILED,
  MSG_IMPERSONATE_FAILED,
} from '@core/constants/messages.constants';
import { IMemberDetail } from '@app/schemas/admin';
import { IUpdateUserProfileRequest } from '@app/schemas/user';
import { IConfirmDialogData } from '@app/schemas/shared';
import { ResetPasswordDialogComponent } from './reset-password-dialog/reset-password-dialog.component';
import { EditProfileDialogComponent } from './edit-profile-dialog/edit-profile-dialog.component';

@Component({
  selector: 'app-admin-member-profile',
  templateUrl: './member-profile.component.html',
  styleUrl: './member-profile.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DatePipe,
    MatButtonModule,
    MatIconModule,
    MatDividerModule,
    MatProgressSpinnerModule,
    FormCardComponent,
  ],
})
export class MemberProfileComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly adminApi = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);

  readonly member = signal<IMemberDetail | null>(null);
  readonly isLoading = signal(false);
  readonly isImpersonating = signal(false);
  readonly badgeMap = BADGE_MAP;

  private userId = '';

  ngOnInit(): void {
    this.userId = this.route.snapshot.params['id'];
    this.loadDetail();
  }

  async loadDetail(): Promise<void> {
    this.isLoading.set(true);
    try {
      const res = await this.adminApi.getMemberDetail(this.userId);
      if (res.success) {
        this.member.set(res.data);
      } else {
        this.snackBar.open(res.message || MSG_ERROR_LOAD_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  goBack(): void {
    this.router.navigate([getRoute('member_controls_member_search').url]);
  }

  getStatusBadge(isActive: boolean): { color: string; bgVar: string; label: string } {
    const key = isActive ? 'active' : 'inactive';
    return { ...this.badgeMap[key], label: isActive ? 'Active' : 'Inactive' };
  }

  toggleStatus(): void {
    const m = this.member();
    if (!m) return;

    const newStatus = !m.is_active;
    const action = newStatus ? 'activate' : 'deactivate';
    const dialogData: IConfirmDialogData = {
      title: `${newStatus ? 'Activate' : 'Deactivate'} User`,
      message: `Are you sure you want to ${action} "${m.first_name} ${m.last_name}" (${m.user_id})?`,
      confirmText: newStatus ? 'Activate' : 'Deactivate',
      color: newStatus ? 'primary' : 'warn',
    };

    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      data: dialogData,
      width: '400px',
    });

    dialogRef.afterClosed().subscribe(async (confirmed: boolean) => {
      if (!confirmed) return;
      try {
        const res = await this.adminApi.toggleUserStatus({
          user_id: this.userId,
          is_active: newStatus,
        });
        if (res.success) {
          this.snackBar.open(MSG_USER_STATUS_UPDATED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
          this.loadDetail();
        } else {
          this.snackBar.open(res.message || MSG_USER_STATUS_UPDATE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        }
      } catch {
        this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    });
  }

  editProfile(): void {
    const m = this.member();
    if (!m) return;

    const dialogRef = this.dialog.open(EditProfileDialogComponent, {
      width: '480px',
      data: m,
    });

    dialogRef.afterClosed().subscribe(async (result: IUpdateUserProfileRequest | null) => {
      if (!result) return;
      try {
        const res = await this.adminApi.updateUserProfile(this.userId, result);
        if (res.success) {
          this.snackBar.open(MSG_USER_PROFILE_UPDATED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
          this.loadDetail();
        } else {
          this.snackBar.open(res.message || MSG_USER_PROFILE_UPDATE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        }
      } catch {
        this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    });
  }

  async openPanel(): Promise<void> {
    this.isImpersonating.set(true);
    try {
      const res = await this.adminApi.impersonateUser(this.userId);
      if (res.success && res.data?.token) {
        this.auth.startImpersonation(res.data.token);
        this.router.navigate([getRoute('user_dashboard').url]);
      } else {
        this.snackBar.open(res.message || MSG_IMPERSONATE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isImpersonating.set(false);
    }
  }

  resetPassword(): void {
    const dialogRef = this.dialog.open(ResetPasswordDialogComponent, {
      width: '400px',
    });

    dialogRef.afterClosed().subscribe(async (newPassword: string | null) => {
      if (!newPassword) return;
      try {
        const res = await this.adminApi.changeUserPassword({
          user_id: this.userId,
          new_password: newPassword,
        });
        if (res.success) {
          this.snackBar.open(MSG_USER_PASSWORD_RESET, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        } else {
          this.snackBar.open(res.message || MSG_USER_PASSWORD_RESET_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        }
      } catch {
        this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    });
  }
}

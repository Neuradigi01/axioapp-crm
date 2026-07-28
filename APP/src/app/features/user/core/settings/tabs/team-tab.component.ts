import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { FurnitureAuthService } from '../../auth/auth.service';
import { commonValidators } from '../../shared/validators';
import { initials } from '@core/services/text.util';
import { extractApiError } from '@core/services/api-error.util';
import {
  DeactivateTargetUser,
  StaffDeactivateModalComponent,
} from '../staff/staff-deactivate-modal.component';
import { StaffWorkloadComponent } from '../staff/staff-workload.component';
import { InvitationRow, InvitationsApiService } from './invitations.service';

interface UserRow {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  role_id: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface RoleRow {
  id: string;
  org_id: string;
  name: string;
  is_system: boolean;
  permission_count: number;
  member_count: number;
}

/**
 * Team tab — manage users in the active org.
 *
 * Reads /api/v1/users + /api/v1/roles and joins them client-side so the
 * row shows the role NAME (the users payload only carries `role_id`).
 *
 * Admins (`users.write`) can edit a user inline (full_name, phone,
 * role) and toggle their is_active flag. Email is immutable —
 * changing email is handled by the invite flow (step 2.5.6, where the
 * Invite-member button gets wired up to it).
 *
 * Users without `users.write` see the list read-only.
 */
@Component({
  selector: 'app-settings-team-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, ReactiveFormsModule, StaffDeactivateModalComponent, StaffWorkloadComponent],
  templateUrl: './team-tab.component.html',
})
export class TeamTabComponent {
  protected readonly initials = initials;
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly fb = inject(FormBuilder);
  private readonly invitationsApi = inject(InvitationsApiService);
  private readonly base = environment.apiBaseUrl;

  protected readonly items = signal<UserRow[]>([]);
  protected readonly roles = signal<RoleRow[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly canWrite = signal(false);
  protected readonly isOwner = signal(false);
  protected readonly currentUserId = signal<string | null>(null);
  protected readonly editingId = signal<string | null>(null);
  protected readonly savingId = signal<string | null>(null);
  protected readonly rowError = signal<{ id: string; message: string } | null>(null);

  // Sub-tab: Users (the existing list) vs Workload. Workload is gated
  // by `users.read`; junior staff without it never see the toggle.
  protected readonly subTab = signal<'users' | 'workload'>('users');

  // Deactivate-modal state (the offboarding two-step flow).
  protected readonly deactivateTarget = signal<DeactivateTargetUser | null>(null);

  // Transfer-ownership modal state
  protected readonly transferModalOpen = signal(false);
  protected readonly transferSubmitting = signal(false);
  protected readonly transferError = signal<string | null>(null);
  protected readonly transferOrgConfirm = signal('');
  protected readonly transferSuccess = signal<string | null>(null);

  // Invite modal + pending list state (step 2.5.6)
  protected readonly invitations = signal<InvitationRow[]>([]);
  protected readonly invitationsError = signal<string | null>(null);
  protected readonly inviteModalOpen = signal(false);
  protected readonly inviteSending = signal(false);
  protected readonly inviteError = signal<string | null>(null);
  protected readonly lastInviteLink = signal<string | null>(null);
  protected readonly revokingInviteId = signal<string | null>(null);

  protected readonly inviteForm = this.fb.nonNullable.group({
    email: ['', [Validators.required, commonValidators.email, commonValidators.maxLength(254)]],
    role_id: ['', Validators.required],
  });

  protected readonly roleNameById = computed(() => {
    const map = new Map<string, string>();
    for (const r of this.roles()) map.set(r.id, r.name);
    return map;
  });

  protected readonly editForm = this.fb.nonNullable.group({
    full_name: ['', [Validators.required, commonValidators.name, Validators.maxLength(255)]],
    phone: ['', [commonValidators.phone()]],
    role_id: ['', Validators.required],
  });

  protected readonly transferForm = this.fb.nonNullable.group({
    target_user_id: ['', Validators.required],
    demote_to_role_id: [''],
  });

  /** Candidate members for transfer — active, not the caller. */
  protected readonly transferTargets = computed(() => {
    const myId = this.currentUserId();
    return this.items().filter((u) => u.id !== myId && u.is_active);
  });

  /** Roles the caller can demote into — anything except Owner. */
  protected readonly demoteRoleOptions = computed(() =>
    this.roles().filter((r) => r.name !== 'Owner'),
  );

  /** Org name typed-confirmation gate. */
  protected readonly currentOrgName = computed(() => this.auth.currentOrg()?.name ?? '');

  protected readonly canSubmitTransfer = computed(() => {
    if (this.transferSubmitting()) return false;
    if (this.transferForm.controls.target_user_id.value === '') return false;
    return this.transferOrgConfirm() === this.currentOrgName();
  });

  constructor() {
    this.reload();
    this.reloadInvitations();
    this.auth
      .me()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (me) => {
          this.canWrite.set(me.permission_keys.includes('users.write'));
          this.isOwner.set(me.role_name === 'Owner');
          this.currentUserId.set(me.id);
        },
        error: () => {
          this.canWrite.set(false);
          this.isOwner.set(false);
          this.currentUserId.set(null);
        },
      });
  }

  protected openTransferModal(): void {
    if (!this.isOwner()) return;
    this.transferForm.reset({ target_user_id: '', demote_to_role_id: '' });
    this.transferOrgConfirm.set('');
    this.transferError.set(null);
    this.transferSuccess.set(null);
    this.transferModalOpen.set(true);
  }

  protected closeTransferModal(): void {
    this.transferModalOpen.set(false);
    this.transferError.set(null);
  }

  protected onTransferOrgConfirmInput(value: string): void {
    this.transferOrgConfirm.set(value);
  }

  protected submitTransfer(): void {
    if (!this.canSubmitTransfer()) return;
    const raw = this.transferForm.getRawValue();
    const body: { target_user_id: string; demote_to_role_id?: string } = {
      target_user_id: raw.target_user_id,
    };
    if (raw.demote_to_role_id) {
      body.demote_to_role_id = raw.demote_to_role_id;
    }
    this.transferSubmitting.set(true);
    this.transferError.set(null);
    this.http
      .post<{ new_owner: { role_id: string }; demoted: { role_id: string } }>(
        `${this.base}/ownership/transfer`,
        body,
      )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.transferSubmitting.set(false);
          const targetEmail =
            this.items().find((u) => u.id === raw.target_user_id)?.email ?? 'the selected member';
          this.transferSuccess.set(
            `Ownership transferred to ${targetEmail}. Your role has changed.`,
          );
          this.transferModalOpen.set(false);
          // Re-read /me so the sidebar + canWrite/isOwner flags reflect
          // the new (demoted) role, then reload the user list.
          this.auth
            .me()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
              next: (me) => {
                this.canWrite.set(me.permission_keys.includes('users.write'));
                this.isOwner.set(me.role_name === 'Owner');
                this.currentUserId.set(me.id);
              },
            });
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.transferSubmitting.set(false);
          this.transferError.set(extractApiError(err) ?? 'Could not transfer ownership.');
        },
      });
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.rowError.set(null);
    forkJoin({
      users: this.http.get<UserRow[]>(`${this.base}/users`),
      roles: this.http.get<RoleRow[]>(`${this.base}/roles`),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ users, roles }) => {
          this.items.set(users);
          this.roles.set(roles);
          // Now that we know the allowed role IDs, layer a picklist
          // validator on both role_id controls so an invalid stale
          // selection can't slip through on save.
          const roleIds = roles.map((r) => r.id);
          this.editForm.controls.role_id.setValidators([
            Validators.required,
            commonValidators.picklist(roleIds),
          ]);
          this.editForm.controls.role_id.updateValueAndValidity({ emitEvent: false });
          this.inviteForm.controls.role_id.setValidators([
            Validators.required,
            commonValidators.picklist(roleIds),
          ]);
          this.inviteForm.controls.role_id.updateValueAndValidity({ emitEvent: false });
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.roles.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load users.');
        },
      });
  }

  protected roleNameOf(user: UserRow): string {
    return this.roleNameById().get(user.role_id) ?? 'No role';
  }

  protected reloadInvitations(): void {
    this.invitationsError.set(null);
    this.invitationsApi
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.invitations.set(rows),
        error: (err: HttpErrorResponse) => {
          this.invitations.set([]);
          // 403 (no users.read) is silent — non-admins shouldn't see
          // this section at all and the UI hides it when canWrite is
          // false. Anything else is a real load failure.
          if (err.status !== 403) {
            this.invitationsError.set(
              extractApiError(err) ?? 'Could not load pending invitations.',
            );
          }
        },
      });
  }

  protected openInviteModal(): void {
    if (!this.canWrite()) return;
    this.inviteForm.reset({ email: '', role_id: '' });
    this.inviteError.set(null);
    this.lastInviteLink.set(null);
    this.inviteModalOpen.set(true);
  }

  protected closeInviteModal(): void {
    this.inviteModalOpen.set(false);
    this.inviteError.set(null);
    this.lastInviteLink.set(null);
  }

  protected sendInvite(): void {
    if (!this.canWrite() || this.inviteForm.invalid || this.inviteSending()) return;
    const { email, role_id } = this.inviteForm.getRawValue();
    this.inviteSending.set(true);
    this.inviteError.set(null);
    this.invitationsApi
      .create(email.trim(), role_id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (inv) => {
          this.inviteSending.set(false);
          this.lastInviteLink.set(inv.accept_link);
          this.inviteForm.reset({ email: '', role_id: '' });
          this.reloadInvitations();
        },
        error: (err: HttpErrorResponse) => {
          this.inviteSending.set(false);
          this.inviteError.set(extractApiError(err) ?? 'Could not send invitation.');
        },
      });
  }

  protected revokeInvite(invitation: InvitationRow): void {
    if (!this.canWrite() || this.revokingInviteId() !== null) return;
    if (!window.confirm(`Revoke invitation for ${invitation.email}?`)) {
      return;
    }
    this.revokingInviteId.set(invitation.id);
    this.invitationsApi
      .revoke(invitation.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.revokingInviteId.set(null);
          this.reloadInvitations();
        },
        error: (err: HttpErrorResponse) => {
          this.revokingInviteId.set(null);
          this.invitationsError.set(extractApiError(err) ?? 'Could not revoke invitation.');
        },
      });
  }

  protected roleNameOfId(roleId: string): string {
    return this.roleNameById().get(roleId) ?? 'Unknown';
  }

  protected copyInviteLink(link: string): void {
    if (!navigator.clipboard) {
      window.prompt('Copy the invite link:', link);
      return;
    }
    void navigator.clipboard.writeText(link);
  }

  protected startEdit(user: UserRow): void {
    this.rowError.set(null);
    this.editForm.reset({
      full_name: user.full_name,
      phone: user.phone ?? '',
      role_id: user.role_id,
    });
    this.editingId.set(user.id);
  }

  protected cancelEdit(): void {
    this.editingId.set(null);
    this.rowError.set(null);
  }

  protected saveEdit(user: UserRow): void {
    if (this.editForm.invalid || this.savingId() !== null) return;
    const raw = this.editForm.getRawValue();
    const phone = raw.phone.trim();
    const body = {
      full_name: raw.full_name.trim(),
      phone: phone.length > 0 ? phone : null,
      role_id: raw.role_id,
    };
    this.savingId.set(user.id);
    this.rowError.set(null);
    this.http
      .patch<UserRow>(`${this.base}/users/${user.id}`, body)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.items.update((rows) => rows.map((r) => (r.id === user.id ? updated : r)));
          this.savingId.set(null);
          this.editingId.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.savingId.set(null);
          this.rowError.set({
            id: user.id,
            message: extractApiError(err) ?? 'Could not save user.',
          });
        },
      });
  }

  protected toggleStatus(user: UserRow): void {
    if (this.savingId() !== null) return;
    // Deactivation goes through the offboarding modal: it fetches
    // open-records-counts and (when total > 0) requires a transfer
    // target so the backend's 409 guard doesn't block the click.
    // Activation stays direct — no transfer needed.
    if (user.is_active) {
      this.openDeactivateModal(user);
      return;
    }
    this.savingId.set(user.id);
    this.rowError.set(null);
    this.http
      .patch<UserRow>(`${this.base}/users/${user.id}/status`, {
        is_active: true,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.items.update((rows) => rows.map((r) => (r.id === user.id ? updated : r)));
          this.savingId.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.savingId.set(null);
          this.rowError.set({
            id: user.id,
            message: extractApiError(err) ?? 'Could not change status.',
          });
        },
      });
  }

  protected openDeactivateModal(user: UserRow): void {
    this.deactivateTarget.set({
      id: user.id,
      full_name: user.full_name,
      email: user.email,
      is_active: user.is_active,
    });
  }

  protected closeDeactivateModal(): void {
    this.deactivateTarget.set(null);
  }

  protected onDeactivationCompleted(): void {
    this.closeDeactivateModal();
    this.reload();
  }

  /** List passed into the deactivate modal so its transfer-target
   * dropdown shows the active teammates. Mirrors `transferTargets`
   * shape but lives here for the modal's narrower API surface. */
  protected readonly deactivateTargetCandidates = computed<DeactivateTargetUser[]>(() =>
    this.items().map((u) => ({
      id: u.id,
      full_name: u.full_name,
      email: u.email,
      is_active: u.is_active,
    })),
  );
}

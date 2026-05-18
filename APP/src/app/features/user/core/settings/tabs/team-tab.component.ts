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
import {
  FormBuilder,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { forkJoin } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { FurnitureAuthService } from '../../auth/auth.service';
import { initials } from '@core/services/text.util';
import {
  InvitationRow,
  InvitationsApiService,
} from './invitations.service';

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
 * Team tab â€” manage users in the active org.
 *
 * Reads /api/v1/users + /api/v1/roles and joins them client-side so the
 * row shows the role NAME (the users payload only carries `role_id`).
 *
 * Admins (`users.write`) can edit a user inline (full_name, phone,
 * role) and toggle their is_active flag. Email is immutable â€”
 * changing email is handled by the invite flow (step 2.5.6, where the
 * Invite-member button gets wired up to it).
 *
 * Users without `users.write` see the list read-only.
 */
@Component({
  selector: 'app-settings-team-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, ReactiveFormsModule],
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
  protected readonly editingId = signal<string | null>(null);
  protected readonly savingId = signal<string | null>(null);
  protected readonly rowError = signal<{ id: string; message: string } | null>(null);

  // Invite modal + pending list state (step 2.5.6)
  protected readonly invitations = signal<InvitationRow[]>([]);
  protected readonly invitationsError = signal<string | null>(null);
  protected readonly inviteModalOpen = signal(false);
  protected readonly inviteSending = signal(false);
  protected readonly inviteError = signal<string | null>(null);
  protected readonly lastInviteLink = signal<string | null>(null);
  protected readonly revokingInviteId = signal<string | null>(null);

  protected readonly inviteForm = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    role_id: ['', Validators.required],
  });

  protected readonly roleNameById = computed(() => {
    const map = new Map<string, string>();
    for (const r of this.roles()) map.set(r.id, r.name);
    return map;
  });

  protected readonly editForm = this.fb.nonNullable.group({
    full_name: ['', [Validators.required, Validators.maxLength(255)]],
    phone: [''],
    role_id: ['', Validators.required],
  });

  constructor() {
    this.reload();
    this.reloadInvitations();
    this.auth
      .me()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (me) => this.canWrite.set(me.permission_keys.includes('users.write')),
        error: () => this.canWrite.set(false),
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
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.roles.set([]);
          this.loading.set(false);
          this.loadError.set(this._extract(err) ?? 'Could not load users.');
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
          // 403 (no users.read) is silent â€” non-admins shouldn't see
          // this section at all and the UI hides it when canWrite is
          // false. Anything else is a real load failure.
          if (err.status !== 403) {
            this.invitationsError.set(
              this._extract(err) ?? 'Could not load pending invitations.',
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
          this.inviteError.set(
            this._extract(err) ?? 'Could not send invitation.',
          );
        },
      });
  }

  protected revokeInvite(invitation: InvitationRow): void {
    if (!this.canWrite() || this.revokingInviteId() !== null) return;
    if (!window.confirm(
      `Revoke invitation for ${invitation.email}?`,
    )) {
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
          this.invitationsError.set(
            this._extract(err) ?? 'Could not revoke invitation.',
          );
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
          this.items.update((rows) =>
            rows.map((r) => (r.id === user.id ? updated : r)),
          );
          this.savingId.set(null);
          this.editingId.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.savingId.set(null);
          this.rowError.set({
            id: user.id,
            message: this._extract(err) ?? 'Could not save user.',
          });
        },
      });
  }

  protected toggleStatus(user: UserRow): void {
    if (this.savingId() !== null) return;
    this.savingId.set(user.id);
    this.rowError.set(null);
    this.http
      .patch<UserRow>(`${this.base}/users/${user.id}/status`, {
        is_active: !user.is_active,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.items.update((rows) =>
            rows.map((r) => (r.id === user.id ? updated : r)),
          );
          this.savingId.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.savingId.set(null);
          this.rowError.set({
            id: user.id,
            message: this._extract(err) ?? 'Could not change status.',
          });
        },
      });
  }

  private _extract(err: HttpErrorResponse): string | null {
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const candidate =
        (body as { message?: string; detail?: unknown }).message
        ?? (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}

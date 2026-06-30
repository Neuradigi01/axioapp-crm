import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router } from '@angular/router';

import { environment } from '../../../../environments/environment';
import { TokenStorageService } from '../../user/core/auth/token-storage.service';
import { extractApiError } from '@core/services/api-error.util';

interface InvitationPreview {
  email: string;
  role_name: string;
  org_name: string;
  org_slug: string;
}

interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
}

/**
 * `/accounts/accept-invite?token=â€¦` â€” recipient-side flow.
 *
 * Three states inside one component:
 *   `loading`  â€” looking up the token via GET /api/v1/invitations/lookup
 *   `invalid`  â€” token missing / expired / already-accepted
 *   `ready`    â€” preview rendered + form open
 *
 * On valid submit the API returns a JWT â€” we persist it via
 * `TokenStorageService` (same path the login flow uses) and redirect
 * to `/user/dashboard`. The recipient never has to log in manually.
 */
@Component({
  selector: 'app-accept-invite',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './accept-invite.component.html',
})
export class AcceptInviteComponent {
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  private readonly storage = inject(TokenStorageService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly base = `${environment.apiBaseUrl}/invitations`;

  protected readonly state = signal<'loading' | 'invalid' | 'ready'>('loading');
  protected readonly invalidReason = signal<string>(
    'This invitation link is invalid or has expired.',
  );
  protected readonly preview = signal<InvitationPreview | null>(null);
  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);
  private rawToken: string | null = null;

  protected readonly form = this.fb.nonNullable.group({
    first_name: ['', [Validators.required, Validators.maxLength(128)]],
    last_name: ['', [Validators.maxLength(128)]],
    phone: [''],
    password: ['', [Validators.required, Validators.minLength(8), Validators.maxLength(255)]],
    confirm_password: ['', [Validators.required]],
  });

  constructor() {
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const token = params.get('token');
      if (!token) {
        this.invalidReason.set('No invitation token in the URL. Ask your admin for a fresh link.');
        this.state.set('invalid');
        return;
      }
      this.rawToken = token;
      this.http
        .get<InvitationPreview>(`${this.base}/lookup`, {
          params: { token },
        })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (info) => {
            this.preview.set(info);
            this.state.set('ready');
          },
          error: (err: HttpErrorResponse) => {
            this.invalidReason.set(
              extractApiError(err) ?? 'This invitation link is invalid or has expired.',
            );
            this.state.set('invalid');
          },
        });
    });
  }

  protected submit(): void {
    if (this.submitting() || this.rawToken === null) return;
    const raw = this.form.getRawValue();
    if (this.form.invalid) {
      this.submitError.set('All required fields must be filled, password â‰¥ 8 chars.');
      return;
    }
    if (raw.password !== raw.confirm_password) {
      this.submitError.set('Password and confirmation do not match.');
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);

    const phone = raw.phone.trim();
    this.http
      .post<LoginResponse>(`${this.base}/accept`, {
        token: this.rawToken,
        password: raw.password,
        first_name: raw.first_name.trim(),
        last_name: raw.last_name.trim(),
        phone: phone.length > 0 ? phone : null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.storage.setTokens(res.access_token, res.access_token);
          void this.router.navigate(['/user']);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Could not accept invitation.');
        },
      });
  }
}

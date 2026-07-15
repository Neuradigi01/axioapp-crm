import { Component, ChangeDetectionStrategy, signal, inject, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { AuthApiService } from '@app/services/auth-api.service';
import { getRoute } from '@core/services/routes-helper.service';

@Component({
  selector: 'app-verify-email',
  templateUrl: './verify-email.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule],
})
export class VerifyEmailComponent implements OnInit {
  private readonly authApi = inject(AuthApiService);
  private readonly route = inject(ActivatedRoute);

  readonly isLoading = signal(true);
  readonly result = signal<'success' | 'error' | null>(null);
  readonly errorMessage = signal('');

  readonly loginUrl = getRoute('login').url;

  ngOnInit(): void {
    const token = this.route.snapshot.queryParamMap.get('token') ?? '';
    if (!token) {
      this.isLoading.set(false);
      this.result.set('error');
      this.errorMessage.set('Invalid verification link. No token provided.');
      return;
    }
    this.verifyEmail(token);
  }

  private async verifyEmail(token: string): Promise<void> {
    try {
      const response = await this.authApi.verifyEmail({ token });
      if (response.success) {
        this.result.set('success');
      } else {
        this.result.set('error');
        this.errorMessage.set(response.message || 'Email verification failed.');
      }
    } catch {
      this.result.set('error');
      this.errorMessage.set('An error occurred during verification. Please try again.');
    } finally {
      this.isLoading.set(false);
    }
  }
}

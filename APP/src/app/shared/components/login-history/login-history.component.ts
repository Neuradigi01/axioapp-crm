import { Component, ChangeDetectionStrategy, inject } from '@angular/core';
import { AuthService } from '@core/services/auth.service';
import { LoginHistoryTableComponent } from '@shared/components/login-history-table/login-history-table.component';

@Component({
  selector: 'app-login-history',
  templateUrl: './login-history.component.html',
  styleUrl: './login-history.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LoginHistoryTableComponent],
})
export class LoginHistoryComponent {
  private readonly auth = inject(AuthService);

  readonly isAdmin = this.auth.isAdmin();
}

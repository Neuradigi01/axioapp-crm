import { Component, ChangeDetectionStrategy, inject, OnInit } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { getRoute } from '@core/services/routes-helper.service';

@Component({
  selector: 'app-email-verification-notice',
  templateUrl: './email-verification-notice.component.html',
  styleUrl: './email-verification-notice.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
  ],
})
export class EmailVerificationNoticeComponent implements OnInit {
  private readonly router = inject(Router);

  readonly email: string = (this.router.currentNavigation()?.extras.state?.['email'] as string) || '';
  readonly loginUrl = getRoute('login').url;

  ngOnInit(): void {
    if (!this.email) {
      this.router.navigate([this.loginUrl]);
    }
  }
}

import { Component, ChangeDetectionStrategy, inject, OnInit } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { getRoute } from '@core/services/routes-helper.service';

@Component({
  selector: 'app-email-verification-notice',
  templateUrl: './email-verification-notice.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule],
})
export class EmailVerificationNoticeComponent implements OnInit {
  private readonly router = inject(Router);

  readonly email: string =
    (this.router.currentNavigation()?.extras.state?.['email'] as string) || '';
  readonly loginUrl = getRoute('login').url;

  ngOnInit(): void {
    if (!this.email) {
      this.router.navigate([this.loginUrl]);
    }
  }
}

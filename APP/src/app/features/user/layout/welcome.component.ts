import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';

import { FurnitureAuthService, MeResponse } from '../core/auth/auth.service';

@Component({
  selector: 'app-furniture-welcome',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './welcome.component.html',
})
export class WelcomeComponent implements OnInit {
  private readonly auth = inject(FurnitureAuthService);

  protected readonly user = signal<MeResponse | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly loading = signal(true);

  ngOnInit(): void {
    this.auth.me().subscribe({
      next: (me) => {
        this.user.set(me);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Could not load your profile.');
        this.loading.set(false);
      },
    });
  }
}

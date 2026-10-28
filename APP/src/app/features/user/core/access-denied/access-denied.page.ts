import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';

import { FurnitureAuthService } from '../auth/auth.service';

/**
 * `/user/access-denied` — landing page when a `permissionGuard(...)`
 * blocks a navigation. Reads `required` (comma-separated permission
 * keys) and `return_url` (the page the user was trying to open) from
 * the query string. Pure presentation — no API calls.
 */
@Component({
  selector: 'app-access-denied-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  templateUrl: './access-denied.page.html',
})
export class AccessDeniedPageComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(FurnitureAuthService);

  protected readonly roleName = this.auth.currentRoleName;

  private readonly params = toSignal(this.route.queryParamMap, {
    initialValue: this.route.snapshot.queryParamMap,
  });

  protected readonly missingKeys = computed(() => {
    const raw = this.params().get('required') ?? '';
    return raw
      .split(',')
      .map((k) => k.trim())
      .filter((k) => k.length > 0);
  });

  protected readonly returnUrl = computed(() => {
    const raw = this.params().get('return_url') ?? '';
    // Only echo back same-origin paths — never a full URL that could
    // be redirected to off-site.
    return /^\/[^/\\]/.test(raw) ? raw : '';
  });
}

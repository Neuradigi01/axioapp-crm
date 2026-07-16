import { HttpClient } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';
import { of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { environment } from '../../../environments/environment';
import { FurnitureAuthService } from '@app/features/user/core/auth/auth.service';
import { getRoute } from '@core/services/routes-helper.service';

import { DemoLoginResponseRow, DemoPreset } from './demo-presets';
import { DemoPresetBusService } from './demo-preset-bus.service';

/**
 * Floating dev-only pill anchored to the bottom-right of the viewport.
 * Loads demo logins once from `/api/v1/_dev/demo-logins`, lets the
 * developer pick one, publishes the selection to DemoPresetBusService,
 * and routes to /accounts/login so the form auto-fills via its effect.
 *
 * Host-site gating (app.html) uses `!environment.production`. Even if
 * the host accidentally renders this component in prod, an empty dev
 * endpoint collapses it to zero DOM (no button, no popover).
 */
@Component({
  selector: 'app-demo-logins-pill',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './demo-logins-pill.component.html',
})
export class DemoLoginsPillComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly bus = inject(DemoPresetBusService);
  private readonly furnitureAuth = inject(FurnitureAuthService);

  protected readonly open = signal(false);
  protected readonly presets = this.bus.presets;
  protected readonly selected = this.bus.selected;
  protected readonly hasPresets = computed(() => this.presets().length > 0);

  ngOnInit(): void {
    if (this.bus.presets().length > 0) return;

    const url = `${environment.apiBaseUrl}/_dev/demo-logins`;
    this.http
      .get<DemoLoginResponseRow[]>(url)
      .pipe(catchError(() => of<DemoLoginResponseRow[]>([])))
      .subscribe((rows) => {
        const presets: DemoPreset[] = rows.map((r) => ({
          label: r.label,
          identifier: r.identifier,
          password: r.password,
          orgSlug: r.org_slug,
        }));
        this.bus.setPresets(presets);
      });
  }

  protected toggle(): void {
    this.open.update((v) => !v);
  }

  protected close(): void {
    this.open.set(false);
  }

  protected pick(preset: DemoPreset): void {
    if (this.furnitureAuth.isAuthenticated()) {
      this.furnitureAuth.clearSession();
    }
    this.bus.apply(preset);
    this.close();
    this.router.navigateByUrl(getRoute('login').url);
  }

  protected onBackdropKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') this.close();
  }
}

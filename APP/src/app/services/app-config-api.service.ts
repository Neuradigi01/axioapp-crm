import { Injectable, inject, signal } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse, IAppConfig } from '@app/schemas/common';

@Injectable({ providedIn: 'root' })
export class AppConfigApiService {
  private readonly http = inject(HttpHelperService);

  private readonly _config = signal<IAppConfig | null>(null);
  readonly config = this._config.asReadonly();

  /** Called once from APP_INITIALIZER — fetches and caches app config. */
  async load(): Promise<void> {
    try {
      const res = await this.http.Get<IAppConfig>('/app-config');
      if (res.success && res.data) {
        this._config.set(res.data);
      }
    } catch {
      // Config load failure — app continues with defaults (null)
    }
  }
}

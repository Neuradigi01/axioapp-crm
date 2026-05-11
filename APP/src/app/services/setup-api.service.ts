import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse } from '@app/schemas/common';
import { IRouteManagement, ISaveRouteRequest } from '@app/schemas/route-management';
import { IEncryptionResult } from '@app/schemas/setup';

@Injectable({ providedIn: 'root' })
export class SetupApiService {
  private readonly http = inject(HttpHelperService);

  // ── Routes Management ────────────────────────────────────────────

  getAllRoutes(): Promise<IApiResponse<IRouteManagement[]>> {
    return this.http.Get<IRouteManagement[]>('/dev/routes/list');
  }

  saveRoute(payload: ISaveRouteRequest): Promise<IApiResponse> {
    return this.http.Post('/dev/routes/save', payload);
  }

  deleteRoute(id: number): Promise<IApiResponse> {
    return this.http.Delete(`/dev/routes/${id}`);
  }

  toggleActiveRoutes(routeIds: number[], isActive: boolean): Promise<IApiResponse> {
    return this.http.Put('/dev/routes/toggle-active', { route_ids: routeIds, is_active: isActive });
  }

  // ── Encryption ───────────────────────────────────────────────────

  encryptText(text: string): Promise<IApiResponse<IEncryptionResult>> {
    return this.http.Get<IEncryptionResult>(`/dev/encryption/encrypt?text=${encodeURIComponent(text)}`);
  }

  decryptText(text: string): Promise<IApiResponse<IEncryptionResult>> {
    return this.http.Get<IEncryptionResult>(`/dev/encryption/decrypt?text=${encodeURIComponent(text)}`);
  }
}

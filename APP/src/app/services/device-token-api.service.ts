import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse } from '@app/schemas/common';
import { IRegisterTokenRequest, IUnregisterTokenRequest } from '@app/schemas/notification';

@Injectable({ providedIn: 'root' })
export class DeviceTokenApiService {
  private readonly http = inject(HttpHelperService);

  registerToken(payload: IRegisterTokenRequest): Promise<IApiResponse<void>> {
    return this.http.Post<void>('/device-tokens/register', payload);
  }

  unregisterToken(payload: IUnregisterTokenRequest): Promise<IApiResponse<void>> {
    return this.http.Post<void>('/device-tokens/unregister', payload);
  }
}

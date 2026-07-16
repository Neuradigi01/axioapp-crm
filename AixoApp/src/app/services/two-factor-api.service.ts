import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse } from '@app/schemas/common';
import { I2faStatus, ISetupAuthenticatorData } from '@app/schemas/user';

@Injectable({ providedIn: 'root' })
export class TwoFactorApiService {
  private readonly http = inject(HttpHelperService);

  getStatus(): Promise<IApiResponse<I2faStatus>> {
    return this.http.Get<I2faStatus>('/2fa/status');
  }

  setupAuthenticator(): Promise<IApiResponse<ISetupAuthenticatorData>> {
    return this.http.Post<ISetupAuthenticatorData>('/2fa/setup-authenticator', {});
  }

  sendSetupOtp(method: string): Promise<IApiResponse> {
    return this.http.Post('/2fa/send-setup-otp', { method });
  }

  verifyAndEnable(payload: { code: string; method: string }): Promise<IApiResponse> {
    return this.http.Post('/2fa/verify-and-enable', payload);
  }

  disable(): Promise<IApiResponse> {
    return this.http.Post('/2fa/disable', {});
  }

  changeMethod(new_method: string): Promise<IApiResponse> {
    return this.http.Post('/2fa/change-method', { new_method });
  }
}

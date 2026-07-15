import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse, IActionVerifyResponse } from '@app/schemas/common';

@Injectable({ providedIn: 'root' })
export class ActionVerifyApiService {
  private readonly http = inject(HttpHelperService);

  sendOtp(method: string): Promise<IApiResponse> {
    return this.http.Post('/action-verify/send-otp', { method });
  }

  verify(code: string, method: string): Promise<IApiResponse<IActionVerifyResponse>> {
    return this.http.Post<IActionVerifyResponse>('/action-verify', { code, method });
  }
}

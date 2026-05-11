import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse } from '@app/schemas/common';
import { ILoginData, ILoginPayload, ITryAnotherWayData, ICaptchaData, IOtpTokenData } from '@app/schemas/auth';


@Injectable({ providedIn: 'root' })
export class AuthApiService {
  private readonly http = inject(HttpHelperService);

  login(payload: ILoginPayload): Promise<IApiResponse<ILoginData>> {
    return this.http.Post<ILoginData>('/auth/login', payload);
  }

  adminLogin(payload: ILoginPayload): Promise<IApiResponse<ILoginData>> {
    return this.http.Post<ILoginData>('/auth/admin-login', payload);
  }

  register(payload: Record<string, unknown>): Promise<IApiResponse<{ user_id?: string }>> {
    return this.http.Post<{ user_id?: string }>('/auth/register', payload);
  }

  forgotPassword(payload: { identifier: string }): Promise<IApiResponse> {
    return this.http.Post('/auth/forgot-password', payload);
  }

  resetPassword(payload: { token: string; new_password: string }): Promise<IApiResponse> {
    return this.http.Post('/auth/reset-password', payload);
  }

  tryAnotherWay(payload: { identifier: string; password: string; user_type: string; method: string }): Promise<IApiResponse<ITryAnotherWayData>> {
    return this.http.Post<ITryAnotherWayData>('/auth/2fa-try-another-way', payload);
  }

  getCaptcha(): Promise<IApiResponse<ICaptchaData>> {
    return this.http.Get<ICaptchaData>('/auth/captcha');
  }

  sendContactOtp(payload: { type: string; value: string }): Promise<IApiResponse<IOtpTokenData>> {
    return this.http.Post<IOtpTokenData>('/auth/verify-contact/send-otp', payload);
  }

  verifyEmail(payload: { token: string }): Promise<IApiResponse> {
    return this.http.Post('/auth/verify-contact/verify-email', payload);
  }

  logout(): Promise<IApiResponse> {
    return this.http.Get('/login-history/logout');
  }
}

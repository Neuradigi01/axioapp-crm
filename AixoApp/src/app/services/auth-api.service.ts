import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AppSettings } from '@app/app.settings';
import { IApiResponse } from '@app/schemas/common';
import {
  ILoginData,
  ILoginPayload,
  ITryAnotherWayData,
  ICaptchaData,
  IOtpTokenData,
} from '@app/schemas/auth';

/**
 * Adapter to the layered `/api/v1/auth/*` endpoints.
 *
 * The new backend returns clean Pydantic models, but every consumer in
 * this codebase still expects the legacy `{success, message, data}`
 * envelope. We translate at this seam so the components stay
 * untouched (including the CLAUDE.md "features/admin/ untouched" set).
 *
 * The base URL used by `HttpHelperService` is `${origin}/api`. We hit
 * `${origin}/api/v1/...` directly here, bypassing that helper.
 */
@Injectable({ providedIn: 'root' })
export class AuthApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${AppSettings.ApiBaseUrl}/v1/auth`;

  async login(payload: ILoginPayload): Promise<IApiResponse<ILoginData>> {
    return this.postUserLogin(`${this.base}/login`, payload);
  }

  async adminLogin(payload: ILoginPayload): Promise<IApiResponse<ILoginData>> {
    // The admin endpoint already returns the legacy envelope (it wraps
    // `login_service.authenticate_admin` server-side), so no adaptation.
    try {
      return await firstValueFrom(
        this.http.post<IApiResponse<ILoginData>>(
          `${this.base}/admin-login`,
          this.toLegacyLoginBody(payload),
        ),
      );
    } catch (err) {
      throw this.normalizeError(err);
    }
  }

  async forgotPassword(payload: { identifier: string }): Promise<IApiResponse> {
    try {
      const res = await firstValueFrom(
        this.http.post<{ message: string }>(`${this.base}/forgot-password`, payload),
      );
      return { success: true, message: res.message, data: null };
    } catch (err) {
      throw this.normalizeError(err);
    }
  }

  async resetPassword(payload: { token: string; new_password: string }): Promise<IApiResponse> {
    try {
      const res = await firstValueFrom(
        this.http.post<{ message: string }>(`${this.base}/reset-password`, payload),
      );
      return { success: true, message: res.message, data: null };
    } catch (err) {
      const norm = this.normalizeError(err);
      if (norm.status >= 400 && norm.status < 500) {
        return { success: false, message: norm.detail, data: null };
      }
      throw err;
    }
  }

  async tryAnotherWay(payload: {
    identifier: string;
    password: string;
    user_type: string;
    method: string;
  }): Promise<IApiResponse<ITryAnotherWayData>> {
    try {
      const res = await firstValueFrom(
        this.http.post<{ method: string; available_methods: string[] }>(
          `${this.base}/2fa/try-another-way`,
          payload,
        ),
      );
      return {
        success: true,
        message: 'OK',
        data: { method: res.method, available_methods: res.available_methods },
      };
    } catch (err) {
      const norm = this.normalizeError(err);
      if (norm.status >= 400 && norm.status < 500) {
        return {
          success: false,
          message: norm.detail,
          data: { method: '', available_methods: [] },
        };
      }
      throw err;
    }
  }

  async getCaptcha(): Promise<IApiResponse<ICaptchaData>> {
    try {
      const res = await firstValueFrom(
        this.http.get<{ type: string; image?: string; token?: string; site_key?: string }>(
          `${this.base}/captcha`,
        ),
      );
      if (res.type === 'none') {
        return {
          success: false,
          message: 'Captcha is disabled',
          data: { type: 'none' } as unknown as ICaptchaData,
        };
      }
      return {
        success: true,
        message: 'OK',
        data: {
          type: res.type,
          image: res.image,
          token: res.token,
          site_key: res.site_key,
        } as unknown as ICaptchaData,
      };
    } catch (err) {
      throw this.normalizeError(err);
    }
  }

  async sendContactOtp(payload: {
    type: string;
    value: string;
  }): Promise<IApiResponse<IOtpTokenData>> {
    try {
      const res = await firstValueFrom(
        this.http.post<{ otp_token: string }>(`${this.base}/verify-contact/send-otp`, payload),
      );
      return {
        success: true,
        message: 'OK',
        data: { otp_token: res.otp_token } as unknown as IOtpTokenData,
      };
    } catch (err) {
      const norm = this.normalizeError(err);
      if (norm.status >= 400 && norm.status < 500) {
        return {
          success: false,
          message: norm.detail,
          data: { otp_token: '' } as unknown as IOtpTokenData,
        };
      }
      throw err;
    }
  }

  async verifyEmail(payload: { token: string }): Promise<IApiResponse> {
    try {
      const res = await firstValueFrom(
        this.http.post<{ message: string }>(`${this.base}/verify-contact/verify-email`, payload),
      );
      return { success: true, message: res.message, data: null };
    } catch (err) {
      const norm = this.normalizeError(err);
      if (norm.status >= 400 && norm.status < 500) {
        return { success: false, message: norm.detail, data: null };
      }
      throw err;
    }
  }

  async logout(): Promise<IApiResponse> {
    // `/login-history/logout` lives under the legacy `common/` router
    // and is outside the auth-cleanup scope.
    return firstValueFrom(
      this.http.get<IApiResponse>(`${AppSettings.ApiBaseUrl}/login-history/logout`),
    );
  }

  // ── private helpers ────────────────────────────────────────────────

  private async postUserLogin(
    url: string,
    payload: ILoginPayload,
  ): Promise<IApiResponse<ILoginData>> {
    const body = {
      email: payload.identifier,
      password: payload.password,
      org_slug: (payload as ILoginPayload & { org_slug?: string }).org_slug,
      two_factor_code: payload.two_factor_code,
      two_factor_method: payload.two_factor_method,
    };
    try {
      const res = await firstValueFrom(this.http.post<Record<string, unknown>>(url, body));
      if (res['requires_two_factor']) {
        return {
          success: false,
          message: '2FA required',
          data: {
            requires_2fa: true,
            method: res['method'] as string,
            available_methods: res['available_methods'] as string[],
          } as unknown as ILoginData,
        };
      }
      return {
        success: true,
        message: 'OK',
        data: {
          token: res['access_token'] as string,
          role: 'User',
        } as unknown as ILoginData,
      };
    } catch (err) {
      const norm = this.normalizeError(err);
      if (norm.status === 401) {
        return { success: false, message: norm.detail, data: null as unknown as ILoginData };
      }
      throw err;
    }
  }

  private toLegacyLoginBody(payload: ILoginPayload): Record<string, unknown> {
    // Phase 5 admin wrapper expects the legacy schema (identifier,
    // device_info, captcha_*, two_factor_*). Pass through verbatim.
    return { ...payload };
  }

  private normalizeError(err: unknown): { status: number; detail: string } {
    if (err instanceof HttpErrorResponse) {
      const detail =
        (err.error?.detail as string) ??
        (err.error?.message as string) ??
        err.message ??
        'Request failed';
      return { status: err.status, detail };
    }
    return { status: 0, detail: 'Unknown error' };
  }
}

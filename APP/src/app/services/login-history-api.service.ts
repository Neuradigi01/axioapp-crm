import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse, IPaginatedApiResponse, ILoginHistoryRecord } from '@app/schemas/common';

@Injectable({ providedIn: 'root' })
export class LoginHistoryApiService {
  private readonly http = inject(HttpHelperService);

  getLoginHistory(payload: {
    user_id?: string;
    match_exact_user_id?: boolean;
    page_index?: number;
    page_size?: number;
  }): Promise<IPaginatedApiResponse<ILoginHistoryRecord>> {
    return this.http.Post('/login-history/list', payload) as Promise<IPaginatedApiResponse<ILoginHistoryRecord>>;
  }

  logoutSession(token_id: number): Promise<IApiResponse> {
    return this.http.Post('/login-history/logout-session', { token_id });
  }
}

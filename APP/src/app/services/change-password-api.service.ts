import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse } from '@app/schemas/common';

@Injectable({ providedIn: 'root' })
export class ChangePasswordApiService {
  private readonly http = inject(HttpHelperService);

  changePassword(payload: { old_password: string; new_password: string }): Promise<IApiResponse> {
    return this.http.Post('/change-password', payload);
  }
}

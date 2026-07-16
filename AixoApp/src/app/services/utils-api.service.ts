import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse } from '@app/schemas/common';

@Injectable({ providedIn: 'root' })
export class UtilsApiService {
  private readonly http = inject(HttpHelperService);

  getQR(text: string, size: number = 200): Promise<IApiResponse<{ qr_image: string }>> {
    return this.http.Get<{ qr_image: string }>(
      `/utils/qr?text=${encodeURIComponent(text)}&size=${size}`,
    );
  }
}

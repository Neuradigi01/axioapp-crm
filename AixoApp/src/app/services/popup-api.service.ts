import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse, IPaginatedApiResponse } from '@app/schemas/common';
import { IPopup, IPopupListRequest } from '@app/schemas/popup';

@Injectable({ providedIn: 'root' })
export class PopupApiService {
  private readonly http = inject(HttpHelperService);

  getPopupList(payload: IPopupListRequest): Promise<IPaginatedApiResponse<IPopup>> {
    return this.http.Post('/admin/popups/list', payload) as Promise<IPaginatedApiResponse<IPopup>>;
  }

  getActivePopup(): Promise<IApiResponse<IPopup | null>> {
    return this.http.Get<IPopup | null>('/popups/active');
  }

  createPopup(file: File, userType: string, title?: string): Promise<IApiResponse<void>> {
    const fields: Record<string, string> = { user_type: userType };
    if (title) fields['title'] = title;
    return this.http.UploadWithFields<void>('/admin/popups/create', file, fields);
  }

  togglePopupStatus(id: number): Promise<IApiResponse<void>> {
    return this.http.Put<void>(`/admin/popups/${id}/toggle-status`, {});
  }

  deletePopup(id: number): Promise<IApiResponse<void>> {
    return this.http.Delete<void>(`/admin/popups/${id}`);
  }
}

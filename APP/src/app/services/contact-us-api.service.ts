import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse, IPaginatedApiResponse } from '@app/schemas/common';
import { IContactUs, IContactUsListRequest } from '@app/schemas/contact-us';

@Injectable({ providedIn: 'root' })
export class ContactUsApiService {
  private readonly http = inject(HttpHelperService);

  submitContactUs(payload: {
    name: string;
    email: string;
    type: string;
    subject: string;
    message: string;
  }): Promise<IApiResponse<void>> {
    return this.http.Post<void>('/misc/contact-us', payload);
  }

  getContactUsList(payload: IContactUsListRequest): Promise<IPaginatedApiResponse<IContactUs>> {
    return this.http.Post('/admin/contact-us/list', payload) as Promise<
      IPaginatedApiResponse<IContactUs>
    >;
  }
}

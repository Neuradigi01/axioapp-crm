import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse, IPaginatedApiResponse } from '@app/schemas/common';
import { INewsletterSubscriber, INewsletterListRequest } from '@app/schemas/newsletter';

@Injectable({ providedIn: 'root' })
export class NewsletterApiService {
  private readonly http = inject(HttpHelperService);

  subscribe(email: string): Promise<IApiResponse<void>> {
    return this.http.Post<void>('/misc/newsletter/subscribe', { email });
  }

  unsubscribe(email: string): Promise<IApiResponse<void>> {
    return this.http.Post<void>('/misc/newsletter/unsubscribe', { email });
  }

  getSubscriberList(
    payload: INewsletterListRequest,
  ): Promise<IPaginatedApiResponse<INewsletterSubscriber>> {
    return this.http.Post('/admin/newsletter/list', payload) as Promise<
      IPaginatedApiResponse<INewsletterSubscriber>
    >;
  }
}

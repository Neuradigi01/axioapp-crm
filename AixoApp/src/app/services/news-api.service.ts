import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse, IPaginatedApiResponse } from '@app/schemas/common';
import { INews, INewsListRequest, ICreateNewsRequest, IUpdateNewsRequest } from '@app/schemas/news';

@Injectable({ providedIn: 'root' })
export class NewsApiService {
  private readonly http = inject(HttpHelperService);

  getNewsList(payload: INewsListRequest): Promise<IPaginatedApiResponse<INews>> {
    return this.http.Post('/admin/news/list', payload) as Promise<IPaginatedApiResponse<INews>>;
  }

  getActiveNews(): Promise<IApiResponse<INews[]>> {
    return this.http.Get<INews[]>('/news/active');
  }

  createNews(payload: ICreateNewsRequest): Promise<IApiResponse<void>> {
    return this.http.Post<void>('/admin/news/create', payload);
  }

  updateNews(id: number, payload: IUpdateNewsRequest): Promise<IApiResponse<void>> {
    return this.http.Put<void>(`/admin/news/${id}`, payload);
  }

  toggleNewsStatus(id: number): Promise<IApiResponse<void>> {
    return this.http.Put<void>(`/admin/news/${id}/toggle-status`, {});
  }

  deleteNews(id: number): Promise<IApiResponse<void>> {
    return this.http.Delete<void>(`/admin/news/${id}`);
  }
}

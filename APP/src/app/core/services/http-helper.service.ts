import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AppSettings } from '@app/app.settings';
import { IApiResponse } from '@app/schemas/common';

@Injectable({ providedIn: 'root' })
export class HttpHelperService {
  private readonly http = inject(HttpClient);

  async Post<T = unknown>(url: string, body: unknown): Promise<IApiResponse<T>> {
    return firstValueFrom(
      this.http.post<IApiResponse<T>>(this.buildUrl(url), body, {
        headers: this.getHeaders(),
      })
    );
  }

  async Get<T = unknown>(url: string): Promise<IApiResponse<T>> {
    return firstValueFrom(
      this.http.get<IApiResponse<T>>(this.buildUrl(url), {
        headers: this.getHeaders(),
      })
    );
  }

  async Put<T = unknown>(url: string, body: unknown): Promise<IApiResponse<T>> {
    return firstValueFrom(
      this.http.put<IApiResponse<T>>(this.buildUrl(url), body, {
        headers: this.getHeaders(),
      })
    );
  }

  async Delete<T = unknown>(url: string): Promise<IApiResponse<T>> {
    return firstValueFrom(
      this.http.delete<IApiResponse<T>>(this.buildUrl(url), {
        headers: this.getHeaders(),
      })
    );
  }

  async Upload<T = unknown>(url: string, file: File, fieldName = 'file'): Promise<IApiResponse<T>> {
    const formData = new FormData();
    formData.append(fieldName, file);

    return firstValueFrom(
      this.http.post<IApiResponse<T>>(this.buildUrl(url), formData)
    );
  }

  async UploadWithFields<T = unknown>(
    url: string, file: File, fields: Record<string, string> = {}, fieldName = 'file'
  ): Promise<IApiResponse<T>> {
    const formData = new FormData();
    formData.append(fieldName, file);
    for (const [key, value] of Object.entries(fields)) {
      formData.append(key, value);
    }

    return firstValueFrom(
      this.http.post<IApiResponse<T>>(this.buildUrl(url), formData)
    );
  }

  async UploadMultiple<T = unknown>(url: string, files: File[], fieldName = 'files'): Promise<IApiResponse<T>> {
    const formData = new FormData();
    for (const file of files) {
      formData.append(fieldName, file);
    }

    return firstValueFrom(
      this.http.post<IApiResponse<T>>(this.buildUrl(url), formData)
    );
  }

  private buildUrl(url: string): string {
    if (url.startsWith('http')) return url;
    return `${AppSettings.ApiBaseUrl}${url.startsWith('/') ? '' : '/'}${url}`;
  }

  private getHeaders(): HttpHeaders {
    return new HttpHeaders({ 'Content-Type': 'application/json' });
  }
}

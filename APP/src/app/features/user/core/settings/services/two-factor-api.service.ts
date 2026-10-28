import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export interface TwoFactorStatus {
  enabled: boolean;
  method: string | null;
}

@Injectable({ providedIn: 'root' })
export class TwoFactorApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/auth/2fa`;

  status(): Observable<TwoFactorStatus> {
    return this.http.get<TwoFactorStatus>(`${this.base}/status`);
  }
}

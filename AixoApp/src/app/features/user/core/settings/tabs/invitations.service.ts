import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export interface InvitationRow {
  id: string;
  email: string;
  role_id: string;
  invited_by: string;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
}

export interface InvitationCreated extends InvitationRow {
  /** Raw accept-link, returned only on POST. Used by the dev UI to
   * surface the link in a toast since the LogEmailBackend doesn't
   * deliver real mail yet. */
  accept_link: string;
}

@Injectable({ providedIn: 'root' })
export class InvitationsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/invitations`;

  list(): Observable<InvitationRow[]> {
    return this.http.get<InvitationRow[]>(this.base);
  }

  create(email: string, role_id: string): Observable<InvitationCreated> {
    return this.http.post<InvitationCreated>(this.base, { email, role_id });
  }

  revoke(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}

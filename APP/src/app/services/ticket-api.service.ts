import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse, IPaginatedApiResponse } from '@app/schemas/common';
import { IAttachment, ITicket, ITicketDetail } from '@app/schemas/ticket';

export interface ITicketListRequest {
  status: string | null;
  search_term: string | null;
  priority?: string | null;
  from_user_id?: string | null;
  page_index: number;
  page_size: number;
}

export interface IComposeTicketRequest {
  subject: string;
  message: string;
  to_user_id?: string;
  attachments: Omit<IAttachment, 'id'>[];
}

export interface IReplyTicketRequest {
  message: string;
  attachments: Omit<IAttachment, 'id'>[];
}

export interface IUpdateTicketStatusRequest {
  status: string;
}

@Injectable({ providedIn: 'root' })
export class TicketApiService {
  private readonly http = inject(HttpHelperService);

  // ── Attachments ──────────────────────────────────────────────────

  uploadAttachments(files: File[]): Promise<IApiResponse<IAttachment[]>> {
    return this.http.UploadMultiple<IAttachment[]>('/attachments/upload', files);
  }

  // ── Ticket Operations ────────────────────────────────────────────

  compose(payload: IComposeTicketRequest): Promise<IApiResponse> {
    return this.http.Post('/tickets/compose', payload);
  }

  getTickets(payload: ITicketListRequest): Promise<IPaginatedApiResponse<ITicket>> {
    return this.http.Post('/tickets/list', payload) as Promise<IPaginatedApiResponse<ITicket>>;
  }

  getTicketDetail(ticketId: number): Promise<IApiResponse<ITicketDetail>> {
    return this.http.Get<ITicketDetail>(`/tickets/${ticketId}`);
  }

  reply(ticketId: number, payload: IReplyTicketRequest): Promise<IApiResponse> {
    return this.http.Post(`/tickets/${ticketId}/reply`, payload);
  }

  updateStatus(ticketId: number, payload: IUpdateTicketStatusRequest): Promise<IApiResponse> {
    return this.http.Put(`/tickets/${ticketId}/status`, payload);
  }
}

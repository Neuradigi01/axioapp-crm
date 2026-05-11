export interface IAttachment {
  id: number;
  file_name: string;
  stored_name: string;
  file_size: number;
  mime_type: string;
}

export interface ITicket {
  id: number;
  ticket_no: string;
  subject: string;
  status: string;
  priority: string;
  from_user_id: string;
  from_user_type: string;
  to_user_id: string | null;
  to_user_type: string;
  created_at: string;
  updated_at: string;
  last_reply_at: string | null;
  has_unread_reply: boolean;
  attachment_count: number;
}

export interface IThreadMessage {
  type: 'message' | 'reply';
  from_id: string;
  from_type: string;
  message: string;
  created_at: string;
  attachments: IAttachment[];
}

export interface ITicketDetail {
  id: number;
  ticket_no: string;
  subject: string;
  status: string;
  priority: string;
  from_user_id: string;
  from_user_type: string;
  to_user_id: string | null;
  to_user_type: string;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  closed_by: string | null;
  thread: IThreadMessage[];
}

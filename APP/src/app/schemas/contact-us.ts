export interface IContactUs {
  id: number;
  name: string;
  email: string;
  type: string;
  subject: string;
  message: string;
  created_at: string;
}

export interface IContactUsListRequest {
  search: string;
  type: string;
  page_index: number;
  page_size: number;
}

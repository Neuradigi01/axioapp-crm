export interface INewsletterSubscriber {
  id: number;
  email: string;
  is_subscribed: boolean;
  created_at: string;
  updated_at: string;
}

export interface INewsletterListRequest {
  search: string;
  status: string;
  page_index: number;
  page_size: number;
}

export interface INews {
  id: number;
  heading: string;
  details: string;
  priority: number;
  user_type: string;
  is_active: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface INewsListRequest {
  search: string;
  status: string;
  user_type: string;
  page_index: number;
  page_size: number;
}

export interface ICreateNewsRequest {
  heading: string;
  details: string;
  priority: number;
  user_type: string;
}

export interface IUpdateNewsRequest {
  heading: string;
  details: string;
  priority: number;
  user_type: string;
}

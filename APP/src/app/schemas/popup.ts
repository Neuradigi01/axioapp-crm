export interface IPopup {
  id: number;
  image_path: string;
  title: string | null;
  user_type: string;
  is_active: boolean;
  created_by: string;
  created_at: string;
}

export interface IPopupListRequest {
  status: string;
  user_type: string;
  page_index: number;
  page_size: number;
}

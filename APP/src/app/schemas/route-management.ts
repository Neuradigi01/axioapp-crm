export interface IRouteManagement {
  id: number;
  parent_id: number;
  control_id: string;
  user_type: string;
  name: string;
  path: string;
  url: string;
  description: string;
  mat_icon: string;
  css_classes: string;
  is_nav_menu_item: boolean;
  order_no: number;
  nav_parent_id: number;
  is_compulsory: boolean;
  is_active: boolean;
}

export interface ISaveRouteRequest {
  id?: number;
  parent_id: number;
  control_id: string;
  user_type: string;
  name: string;
  path: string;
  url: string;
  description?: string;
  mat_icon?: string;
  is_nav_menu_item: boolean;
  order_no: number;
  nav_parent_id: number;
  is_compulsory: boolean;
}

export interface IRouteTreeNode {
  route: IRouteManagement;
  children: IRouteTreeNode[];
  expanded: boolean;
}

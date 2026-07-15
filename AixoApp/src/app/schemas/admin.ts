export interface IAdminProfile {
  admin_user_id: string;
  name: string;
  email: string;
  mobile_no: string | null;
  profile_image: string | null;
}

export interface IAdminDashboardData {
  total_users: number;
  active_users: number;
  today_registrations: number;
  open_tickets: number;
  sub_admin_count: number;
  recent_registrations: IRecentRegistration[];
}

export interface IRecentRegistration {
  user_id: string;
  name: string;
  email: string;
  mobile_no: string | null;
  joining_date: string;
}

// ── Sub-Admin Management ─────────────────────────────────────────────

export interface ISubAdmin {
  admin_user_id: string;
  name: string;
  email: string | null;
  mobile_no: string | null;
  is_active: boolean;
  route_count: number;
  created_at: string;
}

export interface ISubAdminDetail {
  admin_user_id: string;
  name: string;
  email: string | null;
  mobile_no: string | null;
  is_active: boolean;
  route_ids: number[];
}

export interface ISubAdminListRequest {
  search: string | null;
  status: boolean | null;
  page_index: number;
  page_size: number;
}

export interface ICreateSubAdminRequest {
  admin_user_id: string;
  password: string;
  name: string;
  email: string | null;
  mobile_no: string | null;
  route_ids: number[];
}

export interface IUpdateSubAdminRequest {
  name: string;
  email: string | null;
  mobile_no: string | null;
}

export interface IUpdateRoutesRequest {
  admin_id: string;
  route_ids: number[];
}

export interface IToggleStatusRequest {
  admin_id: string;
  is_active: boolean;
}

export interface IAssignableRoute {
  id: number;
  name: string;
  control_id: string;
  parent_id: number;
  nav_parent_id: number;
  is_compulsory: boolean;
}

export interface IRouteTreeNode {
  route: IAssignableRoute;
  children: IRouteTreeNode[];
  checked: boolean;
  indeterminate: boolean;
}

// ── Member (User) Management ────────────────────────────────────────────

export interface IMember {
  user_id: string;
  first_name: string;
  last_name: string;
  email: string;
  mobile_no: string | null;
  is_active: boolean;
  joining_date: string | null;
}

export interface IMemberDetail {
  user_id: string;
  first_name: string;
  last_name: string;
  email: string;
  mobile_no: string | null;
  referral_id: string | null;
  profile_image: string | null;
  joining_date: string | null;
  is_active: boolean;
  two_factor_enabled: boolean;
  two_factor_method: string | null;
  referrer: IMemberReferrer | null;
  total_referrals: number;
  open_tickets: number;
}

export interface IMemberReferrer {
  user_id: string;
  first_name: string;
  last_name: string;
  email: string;
}

export interface IMemberListRequest {
  search: string | null;
  status: boolean | null;
  date_from: string | null;
  date_to: string | null;
  page_index: number;
  page_size: number;
}

export interface IToggleUserStatusRequest {
  user_id: string;
  is_active: boolean;
}

export interface IChangeUserPasswordRequest {
  user_id: string;
  new_password: string;
}

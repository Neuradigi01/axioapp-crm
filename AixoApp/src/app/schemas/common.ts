import { WritableSignal } from '@angular/core';

// ── Shared type aliases ──────────────────────────────────────────────

export type UserType = 'User' | 'Admin';
export type TwoFactorMethod = 'authenticator' | 'email' | 'sms';
export type Theme = 'light' | 'dark';

// ── API response ─────────────────────────────────────────────────────

export interface IApiResponse<T = unknown> {
  success: boolean;
  message: string;
  data: T;
}

export interface IPaginatedApiResponse<T = unknown> extends IApiResponse<T[]> {
  data_count: number;
}

// ── Auth / token ─────────────────────────────────────────────────────

export interface ITokenPayload {
  token_id: number;
  user_id: string;
  role: string;
  access_rights: string;
  is_super_admin?: boolean;
  exp: number;
}

export interface IUserDetails {
  tokenId: number;
  userId: string;
  role: string;
  accessRights: number[];
  isSuperAdmin: boolean;
}

// ── Countdown timer ──────────────────────────────────────────────────

export interface ICountdownTimer {
  remaining: WritableSignal<number>;
  start(seconds: number): void;
  stop(): void;
  destroy(): void;
}

// ── Action verification ──────────────────────────────────────────────

export interface IActionVerifyResponse {
  action_token: string;
}

export interface IActionVerifyDialogData {
  twoFactorMethod: TwoFactorMethod;
  maskedEmail: string | null;
  maskedMobile: string | null;
  availableMethods: TwoFactorMethod[];
}

// ── Location ────────────────────────────────────────────────────────

export interface ICountry {
  id: number;
  name: string;
  iso2: string;
  iso3: string;
  calling_code: string;
  currency: string;
  currency_code: string;
  capital: string;
}

export interface IState {
  id: number;
  country_id: number;
  name: string;
  code: string;
  adm1_code: string;
}

// ── App config ──────────────────────────────────────────────────────

export interface IFirebaseConfig {
  api_key: string;
  auth_domain: string;
  project_id: string;
  messaging_sender_id: string;
  app_id: string;
  vapid_key: string;
}

export interface IAppConfig {
  captcha_enabled: boolean;
  email_enabled: boolean;
  sms_enabled: boolean;
  contact_verification_mode: 'none' | 'pre' | 'post';
  push_notification_enabled: boolean;
  firebase_config: IFirebaseConfig | null;
}

// ── Status badge ─────────────────────────────────────────────────────

export interface IBadgeConfig {
  color: string;
  bgVar: string;
}

// ── Login history ───────────────────────────────────────────────────

export interface ILoginHistoryRecord {
  token_id: number;
  user_id: string;
  user_type: string;
  on_date: string;
  ip_address: string;
  sender_ip: string;
  city: string;
  region: string;
  country: string;
  latitude: string;
  longitude: string;
  device: string;
  device_type: string;
  os: string;
  os_version: string;
  browser: string;
  browser_version: string;
  login_status: string;
  logout_timestamp: string | null;
  by_admin_token_id: number | null;
}

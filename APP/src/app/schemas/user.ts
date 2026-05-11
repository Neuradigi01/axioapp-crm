export interface IUserProfile {
  user_id: string;
  first_name: string;
  last_name: string;
  email: string;
  mobile_no: string | null;
  country_id: number | null;
  state_id: number | null;
  profile_image: string | null;
  referral_id: string;
  joining_date: string | null;
  two_factor_enabled?: boolean;
  two_factor_method?: string | null;
  is_active?: boolean;
}

export interface IUserDashboardData {
  first_name: string;
  last_name: string;
  email: string;
  joining_date: string | null;
  two_factor_enabled: boolean;
  referral_count: number;
  open_tickets: number;
  profile_image: string | null;
}

export interface I2faStatus {
  two_factor_enabled: boolean;
  two_factor_method: string | null;
  masked_email: string | null;
  masked_mobile: string | null;
  email_enabled: boolean;
  sms_enabled: boolean;
}

export interface ISetupAuthenticatorData {
  qr_code: string;
  secret: string;
}

export interface IUpdateUserProfileRequest {
  first_name: string;
  last_name: string;
  email: string;
  mobile_no: string | null;
  country_id: number | null;
  state_id: number | null;
}

export type TfaView = 'loading' | 'disabled' | 'setup-authenticator' | 'setup-otp' | 'enabled' | 'change-method' | 'disable';

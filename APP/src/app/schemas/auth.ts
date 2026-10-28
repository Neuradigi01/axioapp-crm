export interface ILoginData {
  token: string;
  user_id: string;
  role: string;
  first_name?: string;
  last_name?: string;
  name?: string;
  email: string;
  is_super_admin?: boolean;
}

export interface I2faRequiredData {
  requires_2fa: boolean;
  method: string;
  available_methods: string[];
}

export interface ITryAnotherWayData {
  method: string;
  available_methods: string[];
}

export type CaptchaType = 'image' | 'recaptcha_v2' | 'recaptcha_v3';

export interface ICaptchaData {
  type: CaptchaType;
  image?: string;
  token?: string;
  site_key?: string;
}

export interface ILoginPayload {
  identifier: string;
  password: string;
  two_factor_code?: string;
  two_factor_method?: string;
  device_info?: IDeviceInfo;
  captcha_token?: string;
  captcha_answer?: string;
}

export interface IDeviceInfo {
  browser: string;
  browser_version: string;
  device: string;
  device_type: string;
  os: string;
  os_version: string;
  user_agent: string;
}

export interface IOtpTokenData {
  otp_token: string;
}

export interface IEmailVerificationRequiredData {
  requires_email_verification: boolean;
}

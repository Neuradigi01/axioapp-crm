export interface INotification {
  id: number;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

export interface IRegisterTokenRequest {
  fcm_token: string;
  device_info: string | null;
}

export interface IUnregisterTokenRequest {
  fcm_token: string;
}

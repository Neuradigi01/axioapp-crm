import { Injectable, inject, signal } from '@angular/core';
import { initializeApp, FirebaseApp } from 'firebase/app';
import { getMessaging, getToken, onMessage, Messaging, MessagePayload, Unsubscribe } from 'firebase/messaging';
import { IFirebaseConfig } from '@app/schemas/common';
import { DeviceTokenApiService } from '@app/services/device-token-api.service';
import { STORAGE_KEY_FCM_TOKEN } from '@core/constants/app.constants';

@Injectable({ providedIn: 'root' })
export class PushNotificationService {
  private readonly deviceTokenApi = inject(DeviceTokenApiService);
  private firebaseApp: FirebaseApp | null = null;
  private messaging: Messaging | null = null;
  private currentToken: string | null = null;
  private swRegistration: ServiceWorkerRegistration | null = null;
  private initialized = false;

  /** Incremented when a foreground push arrives — bell component watches this to refresh */
  readonly pushReceived = signal(0);

  async initialize(firebaseConfig: IFirebaseConfig): Promise<void> {
    if (this.initialized) return;

    try {
      this.firebaseApp = initializeApp({
        apiKey: firebaseConfig.api_key,
        authDomain: firebaseConfig.auth_domain,
        projectId: firebaseConfig.project_id,
        messagingSenderId: firebaseConfig.messaging_sender_id,
        appId: firebaseConfig.app_id,
      });

      this.messaging = getMessaging(this.firebaseApp);

      this.swRegistration = await navigator.serviceWorker.register('/firebase-messaging-sw.js');
      this.swRegistration.active?.postMessage({
        type: 'FIREBASE_CONFIG',
        config: {
          apiKey: firebaseConfig.api_key,
          authDomain: firebaseConfig.auth_domain,
          projectId: firebaseConfig.project_id,
          messagingSenderId: firebaseConfig.messaging_sender_id,
          appId: firebaseConfig.app_id,
        },
      });

      this.initialized = true;
    } catch (error) {
      console.error('Failed to initialize push notifications:', error);
    }
  }

  async requestPermissionAndRegisterToken(vapidKey: string): Promise<void> {
    if (!this.initialized || !this.messaging) return;

    try {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') return;

      const token = await getToken(this.messaging, {
        vapidKey,
        serviceWorkerRegistration: this.swRegistration!,
      });

      if (!token) return;

      this.currentToken = token;
      sessionStorage.setItem(STORAGE_KEY_FCM_TOKEN, token);
      await this.deviceTokenApi.registerToken({
        fcm_token: token,
        device_info: navigator.userAgent,
      });
    } catch (error) {
      console.error('Failed to register push token:', error);
    }
  }

  async unregisterCurrentToken(): Promise<void> {
    const token = this.currentToken || sessionStorage.getItem(STORAGE_KEY_FCM_TOKEN);
    if (!token) return;

    try {
      await this.deviceTokenApi.unregisterToken({ fcm_token: token });
      this.currentToken = null;
      sessionStorage.removeItem(STORAGE_KEY_FCM_TOKEN);
    } catch (error) {
      console.error('Failed to unregister push token:', error);
    }
  }

  onForegroundMessage(callback: (payload: MessagePayload) => void): Unsubscribe | null {
    if (!this.initialized || !this.messaging) return null;
    return onMessage(this.messaging, (payload) => {
      this.pushReceived.update((v) => v + 1);
      callback(payload);
    });
  }
}

/**
 * Lifecycle wrapper around Meta's Facebook JS SDK for the WhatsApp
 * Embedded Signup popup.
 *
 * Why a separate service:
 *  - The SDK injects a global `<script>` tag and a `window.FB` namespace.
 *    Keeping that side-effect contained in one injectable means the
 *    rest of the SPA never has to know `fbAsyncInit` exists.
 *  - Two parallel async signals (`FB.login` callback + a `postMessage`
 *    event from a `facebook.com` host) must rendezvous before
 *    the orchestration can call the backend. The choreography lives
 *    here, not in the component.
 *
 * Sequence (one `openSignup` call):
 *   1. Lazy-load `https://connect.facebook.net/en_US/sdk.js` on first
 *      use. ~80KB; never loaded on page mount.
 *   2. Call `FB.init({ appId, version })` exactly once per page life.
 *   3. Attach a `window.message` listener filtered to https
 *      `facebook.com` origins to capture the
 *      `{event:'FINISH', data:{phone_number_id, waba_id}}` payload.
 *   4. Call `FB.login(callback, { config_id, response_type:'code',
 *      override_default_response_type:true, extras:{...} })`. The
 *      callback resolves the promise with `code + phone_number_id +
 *      waba_id`; cancel / popup-blocked rejects with a typed reason.
 *   5. Detach the postMessage listener whether success or failure.
 *
 * No external SDK type packages are added — the small bits of the
 * `FB` namespace we touch are declared inline. Keeps the dependency
 * surface minimal.
 */
import { Injectable, signal } from '@angular/core';

export interface EmbeddedSignupResult {
  code: string;
  phoneNumberId: string;
  wabaId: string;
}

export type EmbeddedSignupCancelReason =
  | 'user_cancelled'
  | 'popup_blocked'
  | 'session_info_missing'
  | 'sdk_load_failed';

export class EmbeddedSignupCancelled extends Error {
  constructor(
    public readonly reason: EmbeddedSignupCancelReason,
    message: string,
  ) {
    super(message);
    this.name = 'EmbeddedSignupCancelled';
  }
}

// Minimal type surface for window.FB — only what we call.
interface FBLoginAuthResponse {
  code?: string;
  accessToken?: string;
  userID?: string;
}

interface FBLoginResponse {
  status?: string;
  authResponse?: FBLoginAuthResponse | null;
}

interface FBNamespace {
  init(config: { appId: string; xfbml?: boolean; version: string; cookie?: boolean }): void;
  login(
    callback: (response: FBLoginResponse) => void,
    options: {
      config_id?: string;
      response_type?: string;
      override_default_response_type?: boolean;
      scope?: string;
      extras?: Record<string, unknown>;
    },
  ): void;
}

interface FBWindow extends Window {
  FB?: FBNamespace;
  fbAsyncInit?: () => void;
}

const SDK_SCRIPT_ID = 'whatsapp-fb-jssdk';
const SDK_URL = 'https://connect.facebook.net/en_US/sdk.js';

/** Embedded Signup v4 posts session info from `www.` or `business.`
 *  facebook.com depending on the hosted step, so accept any https
 *  facebook.com host (Meta's reference snippet does the same). */
function isFacebookOrigin(origin: string): boolean {
  try {
    const { protocol, hostname } = new URL(origin);
    return (
      protocol === 'https:' && (hostname === 'facebook.com' || hostname.endsWith('.facebook.com'))
    );
  } catch {
    return false;
  }
}

@Injectable({ providedIn: 'root' })
export class WhatsAppFbSdkService {
  /** True once `FB.init` has run successfully. The component reads
   *  this via the public getter to keep the spinner on while the SDK
   *  loads. */
  private readonly _sdkReady = signal(false);
  readonly sdkReady = this._sdkReady.asReadonly();

  /** Captured between `postMessage` arrival and `FB.login` callback.
   *  Cleared at the end of every `openSignup` run (success or fail)
   *  so a second run starts clean. */
  private sessionInfo: { phoneNumberId: string; wabaId: string } | null = null;

  /** In-flight SDK-load promise — dedupe concurrent `loadSdk` calls
   *  if the user impatient-double-clicks Connect. */
  private loadPromise: Promise<void> | null = null;

  /**
   * Lazy-load the FB JS SDK and run `FB.init`. Safe to call multiple
   * times — the second call returns the already-resolved promise.
   */
  async loadSdk(appId: string, version: string): Promise<void> {
    if (this._sdkReady()) {
      return;
    }
    if (this.loadPromise) {
      return this.loadPromise;
    }

    this.loadPromise = new Promise<void>((resolve, reject) => {
      const w = window as FBWindow;

      const init = (): void => {
        try {
          w.FB?.init({
            appId,
            xfbml: false,
            version,
            cookie: false,
          });
          this._sdkReady.set(true);
          resolve();
        } catch (err) {
          reject(
            new EmbeddedSignupCancelled(
              'sdk_load_failed',
              `FB.init threw: ${err instanceof Error ? err.message : String(err)}`,
            ),
          );
        }
      };

      // If FB is already on window (hot reload, second tab), short-circuit.
      if (w.FB) {
        init();
        return;
      }

      // Standard Meta pattern: define fbAsyncInit BEFORE the script tag
      // so the SDK's onload event finds it.
      w.fbAsyncInit = init;

      // De-dupe the <script> tag — SPA navigation may re-enter this
      // file, and a second tag would re-fire `fbAsyncInit`.
      if (document.getElementById(SDK_SCRIPT_ID)) {
        // Tag already present; wait for the existing one's onload to
        // call our fbAsyncInit. If FB is somehow not yet ready after
        // 10s, surface a load-failure.
        setTimeout(() => {
          if (!this._sdkReady()) {
            reject(
              new EmbeddedSignupCancelled(
                'sdk_load_failed',
                'Facebook SDK script present but FB never initialised.',
              ),
            );
          }
        }, 10_000);
        return;
      }

      const script = document.createElement('script');
      script.id = SDK_SCRIPT_ID;
      script.async = true;
      script.defer = true;
      script.crossOrigin = 'anonymous';
      script.src = SDK_URL;
      script.onerror = () => {
        reject(
          new EmbeddedSignupCancelled(
            'sdk_load_failed',
            'Failed to load the Facebook SDK — check the browser network panel.',
          ),
        );
      };
      document.head.appendChild(script);
    });

    try {
      await this.loadPromise;
    } finally {
      // Clear the promise on terminal state so a retry after failure
      // can re-attempt the load instead of replaying a rejected promise.
      if (!this._sdkReady()) {
        this.loadPromise = null;
      }
    }
  }

  /**
   * Open Meta's Embedded Signup popup and resolve with the harvested
   * `(code, phoneNumberId, wabaId)` on FINISH.
   *
   * Rejects with `EmbeddedSignupCancelled` when:
   *   - the user closes the popup (`authResponse` is null/undefined)
   *   - the browser blocks the popup (FB SDK returns null status)
   *   - the postMessage carrying `phone_number_id` / `waba_id` never
   *     arrives (Meta-side flow aborted before FINISH)
   */
  openSignup(configId: string): Promise<EmbeddedSignupResult> {
    const w = window as FBWindow;
    if (!w.FB) {
      return Promise.reject(
        new EmbeddedSignupCancelled(
          'sdk_load_failed',
          'Facebook SDK not initialised — call loadSdk() first.',
        ),
      );
    }

    return new Promise<EmbeddedSignupResult>((resolve, reject) => {
      this.sessionInfo = null;

      const messageHandler = (event: MessageEvent): void => {
        // Strict origin check — prevents a malicious iframe injecting
        // fake session info from another origin.
        if (!isFacebookOrigin(event.origin)) {
          return;
        }
        let payload: unknown = event.data;
        // Meta sometimes JSON-stringifies the payload; tolerate both.
        if (typeof payload === 'string') {
          try {
            payload = JSON.parse(payload);
          } catch {
            return;
          }
        }
        if (
          !payload ||
          typeof payload !== 'object' ||
          (payload as { type?: string }).type !== 'WA_EMBEDDED_SIGNUP'
        ) {
          return;
        }
        const data = (
          payload as { data?: { phone_number_id?: string; waba_id?: string; event?: string } }
        ).data;
        if (!data) return;
        // FINISH = customer completed all steps; CANCEL = bailed.
        if (data.event === 'FINISH' && data.phone_number_id && data.waba_id) {
          this.sessionInfo = {
            phoneNumberId: data.phone_number_id,
            wabaId: data.waba_id,
          };
        }
      };

      const cleanup = (): void => {
        window.removeEventListener('message', messageHandler);
        this.sessionInfo = null;
      };

      window.addEventListener('message', messageHandler);

      try {
        w.FB!.login(
          (response: FBLoginResponse) => {
            if (!response || !response.authResponse || !response.authResponse.code) {
              // Distinguish popup-blocker (status === null on some
              // browsers when the popup was suppressed) from user-
              // cancel (status === 'unknown' or just missing
              // authResponse with closed popup).
              const status = response?.status;
              const reason: EmbeddedSignupCancelReason =
                status == null ? 'popup_blocked' : 'user_cancelled';
              cleanup();
              reject(
                new EmbeddedSignupCancelled(
                  reason,
                  reason === 'popup_blocked'
                    ? 'Your browser blocked the connection popup. Allow popups for this site and try again.'
                    : 'Connection cancelled.',
                ),
              );
              return;
            }

            const info = this.sessionInfo;
            cleanup();
            if (!info) {
              reject(
                new EmbeddedSignupCancelled(
                  'session_info_missing',
                  'Meta did not return your WhatsApp number details — please retry.',
                ),
              );
              return;
            }

            resolve({
              code: response.authResponse.code,
              phoneNumberId: info.phoneNumberId,
              wabaId: info.wabaId,
            });
          },
          {
            config_id: configId,
            response_type: 'code',
            override_default_response_type: true,
            // Embedded Signup v4 — matches the snippet Meta's Embedded
            // Signup Builder generates for this login configuration.
            extras: {
              version: 'v4',
              sessionInfoVersion: '3',
            },
          },
        );
      } catch (err) {
        cleanup();
        reject(
          new EmbeddedSignupCancelled(
            'sdk_load_failed',
            `FB.login threw: ${err instanceof Error ? err.message : String(err)}`,
          ),
        );
      }
    });
  }
}

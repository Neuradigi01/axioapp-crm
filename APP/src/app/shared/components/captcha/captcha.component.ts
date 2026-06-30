import {
  Component,
  ChangeDetectionStrategy,
  signal,
  output,
  inject,
  OnInit,
  OnDestroy,
  ElementRef,
  viewChild,
} from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { AuthApiService } from '@app/services/auth-api.service';
import { CaptchaType } from '@app/schemas/auth';

declare global {
  interface Window {
    grecaptcha?: {
      render(container: HTMLElement, params: Record<string, unknown>): number;
      reset(widgetId?: number): void;
      execute(siteKey: string, opts: { action: string }): Promise<string>;
      ready(cb: () => void): void;
    };
  }
}

@Component({
  selector: 'app-captcha',
  templateUrl: './captcha.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule],
})
export class CaptchaComponent implements OnInit, OnDestroy {
  private readonly authApi = inject(AuthApiService);

  readonly tokenChange = output<string>();
  readonly typeChange = output<string>();

  readonly captchaType = signal<CaptchaType | ''>('');
  readonly captchaImage = signal('');
  readonly captchaToken = signal('');
  readonly isLoading = signal(false);
  readonly captchaAnswer = new FormControl('');

  private readonly recaptchaContainer = viewChild<ElementRef<HTMLDivElement>>('recaptchaContainer');
  private recaptchaWidgetId: number | null = null;
  private recaptchaSiteKey = '';

  ngOnInit(): void {
    this.loadCaptcha();
  }

  ngOnDestroy(): void {
    this.resetRecaptchaV2Widget();
  }

  async loadCaptcha(): Promise<void> {
    this.isLoading.set(true);
    try {
      const res = await this.authApi.getCaptcha();
      if (res.success && res.data) {
        this.captchaType.set(res.data.type);
        this.typeChange.emit(res.data.type);
        this.recaptchaSiteKey = res.data.site_key || '';

        if (res.data.type === 'image') {
          this.captchaImage.set(res.data.image || '');
          this.captchaToken.set(res.data.token || '');
          this.tokenChange.emit(res.data.token || '');
          this.captchaAnswer.reset();
        } else if (res.data.type === 'recaptcha_v2') {
          await this.initRecaptchaV2();
        } else if (res.data.type === 'recaptcha_v3') {
          await this.initRecaptchaV3();
        }
      }
    } finally {
      this.isLoading.set(false);
    }
  }

  refresh(): void {
    if (this.captchaType() === 'recaptcha_v2') {
      this.resetRecaptchaV2Widget();
      this.renderRecaptchaV2Widget();
    } else if (this.captchaType() === 'recaptcha_v3') {
      this.executeRecaptchaV3();
    } else {
      this.loadCaptcha();
    }
  }

  async execute(): Promise<string> {
    if (this.captchaType() === 'recaptcha_v3') {
      await this.executeRecaptchaV3();
    }
    return this.captchaToken();
  }

  // ── reCAPTCHA v2 (checkbox) ─────────────────────────────────────────

  private async initRecaptchaV2(): Promise<void> {
    await this.loadRecaptchaScript(`https://www.google.com/recaptcha/api.js?render=explicit`);
    setTimeout(() => this.renderRecaptchaV2Widget());
  }

  private renderRecaptchaV2Widget(): void {
    const container = this.recaptchaContainer()?.nativeElement;
    if (!container || !this.recaptchaSiteKey || !window.grecaptcha?.render) return;

    this.resetRecaptchaV2Widget();
    container.innerHTML = '';

    this.recaptchaWidgetId = window.grecaptcha!.render(container, {
      sitekey: this.recaptchaSiteKey,
      callback: (token: string) => {
        this.captchaToken.set(token);
        this.tokenChange.emit(token);
      },
      'expired-callback': () => {
        this.captchaToken.set('');
        this.tokenChange.emit('');
      },
    });
  }

  private resetRecaptchaV2Widget(): void {
    if (this.recaptchaWidgetId !== null && window.grecaptcha?.reset) {
      try {
        window.grecaptcha!.reset(this.recaptchaWidgetId);
      } catch {
        // Widget may already be destroyed
      }
      this.recaptchaWidgetId = null;
    }
    this.captchaToken.set('');
    this.tokenChange.emit('');
  }

  // ── reCAPTCHA v3 (invisible) ────────────────────────────────────────

  private async initRecaptchaV3(): Promise<void> {
    await this.loadRecaptchaScript(
      `https://www.google.com/recaptcha/api.js?render=${this.recaptchaSiteKey}`,
    );
    await this.executeRecaptchaV3();
  }

  private async executeRecaptchaV3(): Promise<void> {
    try {
      const grecaptcha = window.grecaptcha;
      if (!grecaptcha?.execute) return;

      const token: string = await grecaptcha.execute(this.recaptchaSiteKey, { action: 'submit' });
      this.captchaToken.set(token);
      this.tokenChange.emit(token);
    } catch {
      this.captchaToken.set('');
      this.tokenChange.emit('');
    }
  }

  // ── Shared script loader ────────────────────────────────────────────

  private loadRecaptchaScript(src: string): Promise<void> {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src^="${src.split('?')[0]}"]`)) {
        const check = () => {
          if (window.grecaptcha?.ready) {
            window.grecaptcha!.ready(() => resolve());
          } else {
            setTimeout(check, 100);
          }
        };
        check();
        return;
      }

      const script = document.createElement('script');
      script.src = src;
      script.async = true;
      script.defer = true;
      script.onload = () => {
        const check = () => {
          if (window.grecaptcha?.ready) {
            window.grecaptcha!.ready(() => resolve());
          } else {
            setTimeout(check, 100);
          }
        };
        check();
      };
      script.onerror = () => reject(new Error('Failed to load reCAPTCHA script'));
      document.head.appendChild(script);
    });
  }
}

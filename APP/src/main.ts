import { initDebugConsole } from '@neuradigi/debug-console';
import { bootstrapApplication } from '@angular/platform-browser';
import * as Sentry from '@sentry/angular';
import { appConfig } from './app/app.config';
import { App } from './app/app';
import { environment } from './environments/environment';

// Init BEFORE Angular boots so the SDK's global error listeners are in place
// for any startup-time exception. Empty DSN in the environment → no-op (safe
// default for tests + local dev without a Sentry project). Trace sample rate
// is 10% in production so the free-tier quota lasts; 100% in dev so nothing
// is missed during smoke testing.
if (environment.sentryDsn) {
  Sentry.init({
    dsn: environment.sentryDsn,
    environment: environment.sentryEnvironment,
    tracesSampleRate: environment.production ? 0.1 : 1.0,
    integrations: [Sentry.browserTracingIntegration()],
    // Propagate the sentry-trace header only to first-party APIs — avoids
    // leaking trace ids into third-party requests (analytics, ads, etc).
    tracePropagationTargets: [
      'localhost',
      /^https?:\/\/crm-api\.aixoapp\.com/,
      /^https?:\/\/crm-api\.neuradigi\.com/,
    ],
  });
}

// Mount the in-app debug console before Angular boots so console.* output,
// uncaught errors and unhandled rejections are captured from startup. Gated by
// a single flag (OFF in production) — when disabled it patches nothing and
// mounts nothing.
initDebugConsole({ enabled: environment.enableDebugConsole, position: 'top-right' });

bootstrapApplication(App, appConfig).catch((err) => console.error(err));

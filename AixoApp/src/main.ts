import { initDebugConsole } from '@neuradigi/debug-console';
import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';
import { environment } from './environments/environment';

// Mount the in-app debug console before Angular boots so console.* output,
// uncaught errors and unhandled rejections are captured from startup. Gated by
// a single flag (OFF in production) — when disabled it patches nothing and
// mounts nothing.
initDebugConsole({ enabled: environment.enableDebugConsole, position: 'top-right' });

bootstrapApplication(App, appConfig).catch((err) => console.error(err));

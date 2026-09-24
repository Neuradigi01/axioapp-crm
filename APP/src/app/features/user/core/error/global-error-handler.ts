import { ErrorHandler, Injectable } from '@angular/core';
import * as Sentry from '@sentry/angular';

@Injectable({ providedIn: 'root' })
export class GlobalErrorHandler implements ErrorHandler {
  handleError(error: unknown): void {
    console.error('[FurnitureCRM] uncaught error:', error);
    if (error instanceof Error && error.stack) {
      console.error('[FurnitureCRM] stack:\n', error.stack);
    }
    // Forward to Sentry — no-op when Sentry.init() was skipped because
    // environment.sentryDsn is empty. Non-Error throws (a raw string, a
    // rejected fetch response, etc.) are captured as messages so we don't
    // drop the signal.
    if (error instanceof Error) {
      Sentry.captureException(error);
    } else {
      Sentry.captureMessage(String(error), 'error');
    }
  }
}

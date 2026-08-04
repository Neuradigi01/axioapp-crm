import { ErrorHandler, Injectable } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class GlobalErrorHandler implements ErrorHandler {
  handleError(error: unknown): void {
    console.error('[FurnitureCRM] uncaught error:', error);
    if (error instanceof Error && error.stack) {
      console.error('[FurnitureCRM] stack:\n', error.stack);
    }
  }
}

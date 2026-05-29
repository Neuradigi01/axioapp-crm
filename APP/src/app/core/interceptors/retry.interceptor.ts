import {
  HttpErrorResponse,
  HttpInterceptorFn,
  HttpRequest,
} from '@angular/common/http';
import { Observable, of, throwError, timer } from 'rxjs';
import { mergeMap, retry } from 'rxjs/operators';

const RETRYABLE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);
const SKIP_HEADER = 'X-No-Retry';
const MAX_RETRIES = 3;
const BACKOFF_MS = [300, 800, 2000];
const TOTAL_BUDGET_MS = 10_000;
const TRANSIENT_MESSAGE_HINTS = [
  'NETWORK_CHANGED',
  'INTERNET_DISCONNECTED',
  'CONNECTION_RESET',
  'CONNECTION_CLOSED',
  'NAME_NOT_RESOLVED',
];

function isEligible(req: HttpRequest<unknown>): boolean {
  if (!RETRYABLE_METHODS.has(req.method.toUpperCase())) {
    return false;
  }
  if (req.headers.has(SKIP_HEADER)) {
    return false;
  }
  return true;
}

function isTransient(err: unknown): boolean {
  if (!(err instanceof HttpErrorResponse)) {
    return false;
  }
  if (err.status === 0 || err.status === 408 || err.status === 504) {
    return true;
  }
  const message = err.message ?? '';
  return TRANSIENT_MESSAGE_HINTS.some((hint) => message.includes(hint));
}

function waitForOnline(): Observable<unknown> {
  if (typeof navigator === 'undefined' || navigator.onLine) {
    return of(null);
  }
  return new Observable((subscriber) => {
    const handler = () => {
      subscriber.next(null);
      subscriber.complete();
    };
    window.addEventListener('online', handler, { once: true });
    return () => window.removeEventListener('online', handler);
  });
}

export const retryInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isEligible(req)) {
    return next(req);
  }

  const cleanReq = req.headers.has(SKIP_HEADER)
    ? req.clone({ headers: req.headers.delete(SKIP_HEADER) })
    : req;

  const startedAt = Date.now();

  return next(cleanReq).pipe(
    retry({
      count: MAX_RETRIES,
      delay: (err, retryCount) => {
        if (!isTransient(err)) {
          return throwError(() => err);
        }
        if (Date.now() - startedAt > TOTAL_BUDGET_MS) {
          return throwError(() => err);
        }
        const backoff =
          BACKOFF_MS[retryCount - 1] ?? BACKOFF_MS[BACKOFF_MS.length - 1];
        return waitForOnline().pipe(mergeMap(() => timer(backoff)));
      },
    }),
  );
};

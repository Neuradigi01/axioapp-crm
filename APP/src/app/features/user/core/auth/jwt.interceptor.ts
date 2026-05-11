import {
  HttpErrorResponse,
  HttpEvent,
  HttpHandlerFn,
  HttpInterceptorFn,
  HttpRequest,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, catchError, switchMap, throwError } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { TokenStorageService } from './token-storage.service';
import { FurnitureAuthService } from './auth.service';

function ownsRequest(url: string): boolean {
  return url.startsWith(environment.apiBaseUrl) || url.startsWith('/api/v1');
}

function withBearer(req: HttpRequest<unknown>, token: string): HttpRequest<unknown> {
  return req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
}

function tryRefreshAndRetry(
  original: HttpRequest<unknown>,
  next: HttpHandlerFn,
  auth: FurnitureAuthService,
  storage: TokenStorageService,
  router: Router,
): Observable<HttpEvent<unknown>> {
  return auth.refresh().pipe(
    switchMap((res) => next(withBearer(original, res.access_token))),
    catchError((refreshErr) => {
      storage.clear();
      router.navigate(['/accounts/login']);
      return throwError(() => refreshErr);
    }),
  );
}

export const jwtInterceptor: HttpInterceptorFn = (req, next) => {
  if (!ownsRequest(req.url)) {
    return next(req);
  }

  const storage = inject(TokenStorageService);
  const auth = inject(FurnitureAuthService);
  const router = inject(Router);

  const access = storage.getAccess();
  const authedReq = access ? withBearer(req, access) : req;

  // The refresh endpoint must not enter the refresh-on-401 loop itself.
  const isRefreshCall = req.url.endsWith('/auth/refresh');

  return next(authedReq).pipe(
    catchError((error: HttpErrorResponse) => {
      if (error.status !== 401 || isRefreshCall || !access) {
        return throwError(() => error);
      }
      return tryRefreshAndRetry(req, next, auth, storage, router);
    }),
  );
};

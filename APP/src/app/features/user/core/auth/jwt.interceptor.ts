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

function isStaffPortalRequest(url: string): boolean {
  // The staff portal manages its own (scope="staff") token via
  // StaffSessionService. Skipping these URLs here keeps the admin
  // refresh-and-retry path out of the way of a staff 401, and prevents
  // an admin token from being attached to a staff-portal endpoint.
  return url.includes('/staff-portal/');
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
  if (!ownsRequest(req.url) || isStaffPortalRequest(req.url)) {
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
      if (error.status !== 401 || isRefreshCall) {
        return throwError(() => error);
      }
      // No access token in storage but a 401 came back on one of our
      // owned URLs — the session was cleared (another tab logged out,
      // storage got wiped, etc). Send them to login instead of letting
      // the caller surface a raw "Not authenticated" toast.
      if (!access) {
        storage.clear();
        router.navigate(['/accounts/login']);
        return throwError(() => error);
      }
      return tryRefreshAndRetry(req, next, auth, storage, router);
    }),
  );
};

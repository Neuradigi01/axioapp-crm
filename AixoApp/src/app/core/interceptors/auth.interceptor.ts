import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError, switchMap, from } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { AuthService } from '@core/services/auth.service';
import { ActionVerifyService } from '@core/services/action-verify.service';
import {
  SNACKBAR_DURATION,
  SNACKBAR_ACTION,
  ACTION_TOKEN_HEADER,
  ACTION_2FA_ERROR_CODE,
} from '@core/constants/app.constants';
import { MSG_ACTION_VERIFY_CANCELLED, MSG_ACCESS_DENIED } from '@core/constants/messages.constants';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  // FurnitureCRM (Step 1.9) handles `/api/v1/...` via its own jwtInterceptor;
  // this legacy interceptor stays the source of truth for legacy `/api/...` routes.
  if (req.url.includes('/api/v1/')) {
    return next(req);
  }

  const auth = inject(AuthService);
  const snackBar = inject(MatSnackBar);
  const actionVerify = inject(ActionVerifyService);

  const token = auth.getToken();
  let authReq = req;
  if (token) {
    authReq = req.clone({
      setHeaders: { Authorization: `Bearer ${token}` },
    });
  }

  return next(authReq).pipe(
    catchError((error: HttpErrorResponse) => {
      if (error.status === 401) {
        if (auth.isImpersonating()) {
          auth.stopImpersonation();
        } else {
          auth.logout();
        }
      } else if (error.status === 403) {
        const errorCode = error.error?.error_code;
        if (errorCode === ACTION_2FA_ERROR_CODE) {
          return from(actionVerify.getActionToken()).pipe(
            switchMap((actionToken) => {
              if (!actionToken) {
                snackBar.open(MSG_ACTION_VERIFY_CANCELLED, SNACKBAR_ACTION, {
                  duration: SNACKBAR_DURATION,
                  horizontalPosition: 'center',
                  verticalPosition: 'top',
                });
                return throwError(() => error);
              }
              const retryReq = authReq.clone({
                setHeaders: { [ACTION_TOKEN_HEADER]: actionToken },
              });
              return next(retryReq);
            }),
          );
        }
        snackBar.open(MSG_ACCESS_DENIED, SNACKBAR_ACTION, {
          duration: SNACKBAR_DURATION,
          horizontalPosition: 'center',
          verticalPosition: 'top',
        });
      }
      return throwError(() => error);
    }),
  );
};

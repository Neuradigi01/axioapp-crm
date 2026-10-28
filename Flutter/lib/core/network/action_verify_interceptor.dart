import 'dart:async';

import 'package:dio/dio.dart';

import 'package:template_app/core/constants/app_constants.dart';

/// Callback that shows the 2FA dialog and returns an action token, or null if
/// the user cancels. The full UI is implemented in Step 2.6 — until then this
/// returns null (action is cancelled).
typedef ActionTokenResolver = Future<String?> Function();

/// Catches 403 + `2FA_REQUIRED` from ANY API call, prompts the user for a 2FA
/// code via [ActionTokenResolver], and retries the original request with the
/// `X-Action-Token` header.
///
/// This makes 2FA completely transparent to calling code — no screen needs to
/// know about action verification.
class ActionVerifyInterceptor extends Interceptor {
  ActionVerifyInterceptor({
    required Dio dio,
    required ActionTokenResolver actionTokenResolver,
  })  : _dio = dio,
        _actionTokenResolver = actionTokenResolver;

  final Dio _dio;
  final ActionTokenResolver _actionTokenResolver;

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    if (err.response?.statusCode == 403) {
      final responseData = err.response?.data;
      if (responseData is Map<String, dynamic>) {
        final errorCode = responseData['error_code'] as String?;
        if (errorCode == AppConstants.action2faErrorCode) {
          // Ask user for 2FA code via dialog
          final actionToken = await _actionTokenResolver();

          if (actionToken != null && actionToken.isNotEmpty) {
            // Retry the original request with the action token header
            final retryOptions = err.requestOptions;
            retryOptions.headers[AppConstants.actionTokenHeader] = actionToken;

            try {
              final response = await _dio.fetch(retryOptions);
              return handler.resolve(response);
            } on DioException catch (retryError) {
              return handler.reject(retryError);
            }
          }

          // User cancelled — reject with original error
          return handler.reject(err);
        }
      }
    }
    handler.next(err);
  }
}

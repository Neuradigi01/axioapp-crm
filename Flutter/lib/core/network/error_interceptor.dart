import 'dart:developer' as developer;

import 'package:dio/dio.dart';

import 'package:template_app/core/constants/messages.dart';
import 'package:template_app/core/network/api_response.dart';

/// Global error interceptor — normalises network / timeout / server errors
/// into [DioException] with a user-friendly message.
///
/// Placed last in the interceptor chain so auth and action-verify run first.
class ErrorInterceptor extends Interceptor {
  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final String message;

    switch (err.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        message = Messages.requestTimeout;
      case DioExceptionType.connectionError:
        message = Messages.noInternetConnection;
      case DioExceptionType.badResponse:
        message = _extractMessage(err.response);
      case DioExceptionType.cancel:
        // Request was cancelled — pass through silently
        return handler.next(err);
      default:
        message = Messages.errorGeneric;
    }

    developer.log(
      'HTTP Error: ${err.requestOptions.method} ${err.requestOptions.path} — $message',
      name: 'ErrorInterceptor',
      error: err.error,
    );

    handler.next(
      err.copyWith(message: message),
    );
  }

  /// Tries to pull the `message` field from a standard [ApiResponse]-shaped
  /// body; falls back to a generic message.
  String _extractMessage(Response<dynamic>? response) {
    if (response?.data is Map<String, dynamic>) {
      final data = response!.data as Map<String, dynamic>;
      final apiResponse = ApiResponse.fromJson(data);
      if (apiResponse.message.isNotEmpty) return apiResponse.message;
    }
    return Messages.errorGeneric;
  }
}

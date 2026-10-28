import 'package:dio/dio.dart';

import 'package:template_app/core/config/app_config.dart';
import 'package:template_app/core/network/action_verify_interceptor.dart';
import 'package:template_app/core/network/auth_interceptor.dart';
import 'package:template_app/core/network/error_interceptor.dart';

/// Creates and configures the [Dio] instance used throughout the app.
///
/// Interceptor order: AuthInterceptor → ActionVerifyInterceptor → ErrorInterceptor
Dio createDio({
  required AuthInterceptor authInterceptor,
  required ActionVerifyInterceptor actionVerifyInterceptor,
}) {
  final dio = Dio(
    BaseOptions(
      baseUrl: AppConfig.apiBaseUrl,
      connectTimeout: const Duration(milliseconds: AppConfig.connectTimeoutMs),
      receiveTimeout: const Duration(milliseconds: AppConfig.requestTimeoutMs),
      sendTimeout: const Duration(milliseconds: AppConfig.requestTimeoutMs),
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
    ),
  );

  // Order matters: auth first, then action-verify, then error handling last
  dio.interceptors.addAll([
    authInterceptor,
    actionVerifyInterceptor,
    ErrorInterceptor(),
  ]);

  return dio;
}

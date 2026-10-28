import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'package:template_app/core/network/action_verify_interceptor.dart';
import 'package:template_app/core/network/api_helper.dart';
import 'package:template_app/core/network/auth_interceptor.dart';
import 'package:template_app/core/network/dio_provider.dart';
import 'package:template_app/core/services/action_verify_service.dart';
import 'package:template_app/core/services/auth_service.dart';
import 'package:template_app/core/services/routes_helper_service.dart';
import 'package:template_app/providers/router_provider.dart';
import 'package:template_app/services/action_verify_api_service.dart';
import 'package:template_app/services/app_config_api_service.dart';
import 'package:template_app/services/auth_api_service.dart';
import 'package:template_app/services/location_api_service.dart';
import 'package:template_app/services/change_password_api_service.dart';
import 'package:template_app/services/login_history_api_service.dart';
import 'package:template_app/services/two_factor_api_service.dart';
import 'package:template_app/services/user_api_service.dart';

// ── Secure Storage ──────────────────────────────────────────────────────────

final secureStorageProvider = Provider<FlutterSecureStorage>((ref) {
  return const FlutterSecureStorage();
});

// ── Auth Service ────────────────────────────────────────────────────────────

final authServiceProvider = Provider<AuthService>((ref) {
  final storage = ref.read(secureStorageProvider);
  return AuthService(storage);
});

// ── Routes Helper ───────────────────────────────────────────────────────────

final routesHelperProvider = Provider<RoutesHelperService>((ref) {
  return RoutesHelperService();
});

// ── Dio & ApiHelper ─────────────────────────────────────────────────────────

/// Provides the configured [Dio] instance.
///
/// Reads the cached token synchronously from [AuthService] and triggers
/// logout via the auth provider on 401.
final dioProvider = Provider<Dio>((ref) {
  final authService = ref.read(authServiceProvider);

  String? readToken() => authService.cachedToken;

  // Logout callback — clears stored session data.
  // Full state reset (AuthNotifier.logout) is handled at the provider level
  // when screens detect the cleared state.
  void onLogout() {
    authService.clearAll();
  }

  final authInterceptor = AuthInterceptor(
    tokenReader: readToken,
    onLogout: onLogout,
  );

  // Create Dio with a placeholder interceptor first
  final dio = createDio(
    authInterceptor: authInterceptor,
    actionVerifyInterceptor: ActionVerifyInterceptor(
      dio: Dio(),
      actionTokenResolver: () async => null,
    ),
  );

  // Build ActionVerifyService directly here to avoid circular provider deps.
  // (dioProvider → apiHelper → actionVerifyApiService → actionVerifyService
  //  would create a cycle if wired via providers.)
  final actionVerifyApiService = ActionVerifyApiService(ApiHelper(dio));
  final navigatorKey = ref.read(rootNavigatorKeyProvider);
  final actionVerifyService = ActionVerifyService(
    apiService: actionVerifyApiService,
    navigatorKey: navigatorKey,
  );

  Future<String?> resolveActionToken() async {
    return actionVerifyService.getActionToken();
  }

  // Replace the placeholder with the real interceptor that references
  // the actual Dio instance (needed to retry requests).
  dio.interceptors.removeWhere((i) => i is ActionVerifyInterceptor);
  dio.interceptors.insert(
    1, // After AuthInterceptor, before ErrorInterceptor
    ActionVerifyInterceptor(
      dio: dio,
      actionTokenResolver: resolveActionToken,
    ),
  );

  return dio;
});

/// Provides the [ApiHelper] wrapping Dio for typed API calls.
final apiHelperProvider = Provider<ApiHelper>((ref) {
  final dio = ref.read(dioProvider);
  return ApiHelper(dio);
});

// ── Feature API Services ───────────────────────────────────────────────────

/// Provides the [AuthApiService] for authentication endpoints.
final authApiServiceProvider = Provider<AuthApiService>((ref) {
  final apiHelper = ref.read(apiHelperProvider);
  return AuthApiService(apiHelper);
});

/// Provides the [AppConfigApiService] for app configuration.
final appConfigApiServiceProvider = Provider<AppConfigApiService>((ref) {
  final apiHelper = ref.read(apiHelperProvider);
  return AppConfigApiService(apiHelper);
});

/// Provides the [LocationApiService] for country/state endpoints.
final locationApiServiceProvider = Provider<LocationApiService>((ref) {
  final apiHelper = ref.read(apiHelperProvider);
  return LocationApiService(apiHelper);
});

/// Provides the [UserApiService] for user profile and dashboard endpoints.
final userApiServiceProvider = Provider<UserApiService>((ref) {
  final apiHelper = ref.read(apiHelperProvider);
  return UserApiService(apiHelper);
});

/// Provides the [TwoFactorApiService] for 2FA management endpoints.
final twoFactorApiServiceProvider = Provider<TwoFactorApiService>((ref) {
  final apiHelper = ref.read(apiHelperProvider);
  return TwoFactorApiService(apiHelper);
});

/// Provides the [LoginHistoryApiService] for login history endpoints.
final loginHistoryApiServiceProvider =
    Provider<LoginHistoryApiService>((ref) {
  final apiHelper = ref.read(apiHelperProvider);
  return LoginHistoryApiService(apiHelper);
});

/// Provides the [ChangePasswordApiService] for change password endpoint.
final changePasswordApiServiceProvider =
    Provider<ChangePasswordApiService>((ref) {
  final apiHelper = ref.read(apiHelperProvider);
  return ChangePasswordApiService(apiHelper);
});

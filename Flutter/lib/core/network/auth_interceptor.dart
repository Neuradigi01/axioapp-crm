import 'package:dio/dio.dart';

/// Callback type for reading the current JWT token.
typedef TokenReader = String? Function();

/// Callback type for handling forced logout (e.g., on 401).
typedef LogoutCallback = void Function();

/// Attaches JWT Bearer token to outgoing requests and handles 401 responses.
///
/// - Adds `Authorization: Bearer <token>` header when a token is available.
/// - On 401 response, triggers logout so the user is redirected to login.
class AuthInterceptor extends Interceptor {
  AuthInterceptor({
    required TokenReader tokenReader,
    required LogoutCallback onLogout,
  })  : _tokenReader = tokenReader,
        _onLogout = onLogout;

  final TokenReader _tokenReader;
  final LogoutCallback _onLogout;

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    final token = _tokenReader();
    if (token != null && token.isNotEmpty) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    if (err.response?.statusCode == 401) {
      _onLogout();
    }
    handler.next(err);
  }
}

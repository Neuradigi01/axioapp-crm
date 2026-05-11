import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:template_app/core/services/auth_service.dart';
import 'package:template_app/providers/service_providers.dart';

// ── Auth State ──────────────────────────────────────────────────────────────

class AuthState {
  const AuthState({
    this.isAuthenticated = false,
    this.isLoading = false,
    this.token,
    this.userId,
    this.role,
    this.accessRights = const [],
    this.errorMessage,
  });

  final bool isAuthenticated;
  final bool isLoading;
  final String? token;
  final String? userId;
  final String? role;
  final List<String> accessRights;
  final String? errorMessage;

  AuthState copyWith({
    bool? isAuthenticated,
    bool? isLoading,
    String? token,
    String? userId,
    String? role,
    List<String>? accessRights,
    String? errorMessage,
  }) {
    return AuthState(
      isAuthenticated: isAuthenticated ?? this.isAuthenticated,
      isLoading: isLoading ?? this.isLoading,
      token: token ?? this.token,
      userId: userId ?? this.userId,
      role: role ?? this.role,
      accessRights: accessRights ?? this.accessRights,
      errorMessage: errorMessage,
    );
  }
}

// ── Auth Notifier ───────────────────────────────────────────────────────────

class AuthNotifier extends StateNotifier<AuthState> {
  AuthNotifier(this._authService) : super(const AuthState());

  final AuthService _authService;

  /// Attempts to restore session from secure storage on app startup.
  Future<void> tryRestoreSession() async {
    state = state.copyWith(isLoading: true);

    final token = await _authService.getToken();
    if (token == null || token.isEmpty) {
      state = const AuthState();
      return;
    }

    final userData = await _authService.getUserData();
    state = AuthState(
      isAuthenticated: true,
      token: token,
      userId: userData['userId'] as String?,
      role: userData['role'] as String?,
      accessRights: userData['accessRights'] as List<String>,
    );
  }

  /// Saves credentials after a successful login API call.
  Future<void> login({
    required String token,
    required String userId,
    required String role,
    required List<String> accessRights,
  }) async {
    state = state.copyWith(isLoading: true);

    await _authService.saveToken(token);
    await _authService.saveUserData(
      userId: userId,
      role: role,
      accessRights: accessRights,
    );

    state = AuthState(
      isAuthenticated: true,
      token: token,
      userId: userId,
      role: role,
      accessRights: accessRights,
    );
  }

  /// Clears all session data and resets state.
  Future<void> logout() async {
    await _authService.clearAll();
    state = const AuthState();
  }

  /// Sets an error message (e.g., from a failed login attempt).
  void setError(String message) {
    state = state.copyWith(
      isLoading: false,
      errorMessage: message,
    );
  }

  /// Clears the current error message.
  void clearError() {
    state = state.copyWith(errorMessage: null);
  }
}

// ── Provider ────────────────────────────────────────────────────────────────

final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  final authService = ref.read(authServiceProvider);
  return AuthNotifier(authService);
});

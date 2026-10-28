import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'package:template_app/core/constants/app_constants.dart';

/// Manages JWT token storage and user session data using secure storage.
class AuthService {
  AuthService(this._storage);

  final FlutterSecureStorage _storage;

  // ── Storage keys ──────────────────────────────────────────────────────
  static const _keyUserId = 'user_id';
  static const _keyRole = 'user_role';
  static const _keyAccessRights = 'access_rights';

  // ── Token cache (avoids async reads in interceptor) ───────────────────
  String? _cachedToken;

  /// Returns the cached token synchronously (for use in interceptors).
  String? get cachedToken => _cachedToken;

  // ── Token ─────────────────────────────────────────────────────────────

  Future<void> saveToken(String token) async {
    _cachedToken = token;
    await _storage.write(
      key: AppConstants.storageKeyToken,
      value: token,
    );
  }

  Future<String?> getToken() async {
    _cachedToken = await _storage.read(key: AppConstants.storageKeyToken);
    return _cachedToken;
  }

  Future<void> clearToken() async {
    _cachedToken = null;
    await _storage.delete(key: AppConstants.storageKeyToken);
  }

  // ── User data ─────────────────────────────────────────────────────────

  Future<void> saveUserData({
    required String userId,
    required String role,
    required List<String> accessRights,
  }) async {
    await Future.wait([
      _storage.write(key: _keyUserId, value: userId),
      _storage.write(key: _keyRole, value: role),
      _storage.write(
        key: _keyAccessRights,
        value: jsonEncode(accessRights),
      ),
    ]);
  }

  Future<Map<String, dynamic>> getUserData() async {
    final results = await Future.wait([
      _storage.read(key: _keyUserId),
      _storage.read(key: _keyRole),
      _storage.read(key: _keyAccessRights),
    ]);

    List<String> accessRights = [];
    final rightsJson = results[2];
    if (rightsJson != null && rightsJson.isNotEmpty) {
      accessRights = List<String>.from(jsonDecode(rightsJson) as List);
    }

    return {
      'userId': results[0],
      'role': results[1],
      'accessRights': accessRights,
    };
  }

  // ── Session management ────────────────────────────────────────────────

  Future<void> clearAll() async {
    _cachedToken = null;
    await Future.wait([
      _storage.delete(key: AppConstants.storageKeyToken),
      _storage.delete(key: _keyUserId),
      _storage.delete(key: _keyRole),
      _storage.delete(key: _keyAccessRights),
    ]);
  }

  Future<bool> get isAuthenticated async {
    final token = await getToken();
    return token != null && token.isNotEmpty;
  }
}

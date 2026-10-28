import 'package:flutter/material.dart';

import 'package:template_app/core/constants/app_constants.dart';
import 'package:template_app/services/action_verify_api_service.dart';
import 'package:template_app/shared/widgets/action_verify_dialog.dart';

/// Orchestrates the action verification (2FA) flow.
///
/// Called by [ActionVerifyInterceptor] when an API returns 403 + 2FA_REQUIRED.
/// Shows the [ActionVerifyDialog] and returns the action token on success.
class ActionVerifyService {
  ActionVerifyService({
    required this.apiService,
    required this.navigatorKey,
  });

  final ActionVerifyApiService apiService;
  final GlobalKey<NavigatorState> navigatorKey;

  /// Shows the 2FA dialog and returns an action token, or null if cancelled.
  ///
  /// 1. Fetches the user's 2FA status (available methods)
  /// 2. Shows [ActionVerifyDialog] as a modal
  /// 3. Returns action_token string on success, null on cancel/failure
  Future<String?> getActionToken() async {
    final context = navigatorKey.currentContext;
    if (context == null) return null;

    // Fetch 2FA status to know available methods
    final statusResponse = await apiService.getTfaStatus();
    if (!statusResponse.success) return null;

    final data = statusResponse.data as Map<String, dynamic>?;
    if (data == null) return null;

    final isEnabled = data['is_enabled'] as bool? ?? false;
    if (!isEnabled) return null;

    final currentMethod = data['method'] as String? ??
        AppConstants.tfaMethodAuthenticator;

    // Build available methods list
    final availableMethods = <String>[];
    final methods = data['available_methods'] as List<dynamic>?;
    if (methods != null) {
      for (final m in methods) {
        if (m is String) availableMethods.add(m);
      }
    }

    // Fallback: if no methods returned, use current method
    if (availableMethods.isEmpty) {
      availableMethods.add(currentMethod);
    }

    final maskedEmail = data['masked_email'] as String?;
    final maskedPhone = data['masked_phone'] as String?;

    // Re-check context after async gap
    final dialogContext = navigatorKey.currentContext;
    if (dialogContext == null) return null;

    // Show the dialog
    final actionToken = await showDialog<String?>(
      context: dialogContext,
      barrierDismissible: false,
      builder: (_) => ActionVerifyDialog(
        apiService: apiService,
        availableMethods: availableMethods,
        defaultMethod: currentMethod,
        maskedEmail: maskedEmail,
        maskedPhone: maskedPhone,
      ),
    );

    return actionToken;
  }
}

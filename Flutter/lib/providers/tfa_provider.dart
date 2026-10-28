import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:template_app/models/tfa_status.dart';
import 'package:template_app/providers/service_providers.dart';

/// Provides the user's current 2FA status.
///
/// Fetches once and caches. Use `ref.invalidate(tfaStatusProvider)` to refresh.
final tfaStatusProvider = FutureProvider<TfaStatus?>((ref) async {
  final tfaApi = ref.read(twoFactorApiServiceProvider);
  final response = await tfaApi.getStatus();

  if (!response.success || response.data == null) {
    return null;
  }

  return TfaStatus.fromJson(response.data as Map<String, dynamic>);
});

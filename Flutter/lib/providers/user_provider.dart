import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:template_app/models/dashboard_data.dart';
import 'package:template_app/models/user_profile.dart';
import 'package:template_app/providers/service_providers.dart';

/// Provides the user's dashboard summary data.
///
/// Fetches once and caches. Use `ref.invalidate(dashboardProvider)` to refresh.
final dashboardProvider = FutureProvider<DashboardData?>((ref) async {
  final userApi = ref.read(userApiServiceProvider);
  final response = await userApi.getDashboard();

  if (!response.success || response.data == null) {
    return null;
  }

  return DashboardData.fromJson(response.data as Map<String, dynamic>);
});

/// Provides the user's full profile.
///
/// Fetches once and caches. Use `ref.invalidate(userProfileProvider)` to refresh.
final userProfileProvider = FutureProvider<UserProfile?>((ref) async {
  final userApi = ref.read(userApiServiceProvider);
  final response = await userApi.getProfile();

  if (!response.success || response.data == null) {
    return null;
  }

  return UserProfile.fromJson(response.data as Map<String, dynamic>);
});

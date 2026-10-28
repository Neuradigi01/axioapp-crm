import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:template_app/core/router/app_router.dart';

/// Global navigator key shared with GoRouter and services that need
/// to show dialogs from outside the widget tree (e.g., ActionVerifyService).
final rootNavigatorKeyProvider = Provider<GlobalKey<NavigatorState>>((ref) {
  return GlobalKey<NavigatorState>();
});

/// Provides the [GoRouter] instance for the application.
final routerProvider = Provider<GoRouter>((ref) {
  final navigatorKey = ref.read(rootNavigatorKeyProvider);
  return createAppRouter(ref, navigatorKey: navigatorKey);
});

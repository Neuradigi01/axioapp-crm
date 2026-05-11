import 'package:flutter/material.dart';

import '../../core/constants/app_constants.dart';
import '../../core/theme/app_dimensions.dart';
import '../widgets/theme_toggle_widget.dart';

/// Layout shell for auth screens (login, register, forgot password, etc.).
///
/// Provides an AppBar with app name and theme toggle, centered scrollable
/// content area constrained to [AppDimensions.authCardMaxWidth].
class AuthLayout extends StatelessWidget {
  const AuthLayout({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text(AppConstants.appName),
        centerTitle: true,
        actions: const [
          ThemeToggleWidget(),
        ],
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppDimensions.lg),
          child: ConstrainedBox(
            constraints: const BoxConstraints(
              maxWidth: AppDimensions.authCardMaxWidth,
            ),
            child: child,
          ),
        ),
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../core/constants/app_routes.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../shared/widgets/app_button.dart';
import '../widgets/auth_card_widget.dart';

class EmailVerificationNoticeScreen extends StatelessWidget {
  const EmailVerificationNoticeScreen({super.key, this.extra});

  /// Data passed from the login screen via GoRouter extra.
  /// Expected key: `email` — the email address to display.
  final Map<String, dynamic>? extra;

  @override
  Widget build(BuildContext context) {
    final email = extra?['email'] as String?;

    // No email in state — redirect to login
    if (email == null || email.isEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (context.mounted) context.goNamed(AppRoutes.login);
      });
      return const SizedBox.shrink();
    }

    final theme = Theme.of(context);

    return AuthCardWidget(
      title: 'Verify Your Email',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          // Email icon
          Icon(
            Icons.mark_email_unread_outlined,
            size: 64,
            color: theme.colorScheme.primary,
          ),
          const SizedBox(height: AppDimensions.lg),

          // Message
          Text(
            'A verification email has been sent to',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: AppDimensions.xs),
          Text(
            email,
            style: theme.textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w600,
            ),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: AppDimensions.sm),
          Text(
            'Please check your inbox and click the verification link to activate your account.',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: AppDimensions.xl),

          // Back to Login button
          AppButton(
            label: 'Back to Login',
            onPressed: () => context.goNamed(AppRoutes.login),
          ),
        ],
      ),
    );
  }
}

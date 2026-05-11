import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../core/constants/app_routes.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../shared/widgets/app_card.dart';
import '../../shared/widgets/login_history_table_widget.dart';
import '../../shared/widgets/tfa_settings_widget.dart';

/// Security settings screen combining 2FA settings and recent login history.
class SecurityScreen extends StatelessWidget {
  const SecurityScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppDimensions.md),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: AppDimensions.formMaxWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Section 1: 2FA Settings
              const TfaSettingsWidget(),
              const SizedBox(height: AppDimensions.lg),

              // Section 2: Recent Login History
              AppCard(
                title: 'Recent Login History',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const LoginHistoryTableWidget(),
                    const SizedBox(height: AppDimensions.md),
                    Align(
                      alignment: Alignment.centerRight,
                      child: TextButton.icon(
                        onPressed: () =>
                            context.goNamed(AppRoutes.userLoginHistory),
                        icon: const Icon(Icons.history, size: 18),
                        label: Text(
                          'View All Login History',
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: theme.colorScheme.primary,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
